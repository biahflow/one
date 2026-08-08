# ADR 0045 — O worker que cabia no Cloud Run

**Status:** aceito
**Data:** 07/08/2026
**Substitui:** a decisão de VM da primeira versão do Terraform de HML

## Contexto

O Terraform de HML nasceu com uma VM hospedando Redis, o worker e o beat do Celery. A
justificativa escrita no módulo era esta:

> `celery worker` e `celery beat` não escutam porta nenhuma, e um serviço Cloud Run cuja imagem
> não responde em `$PORT` dentro do tempo de boot tem a revisão **recusada**.

A premissa é verdadeira e a conclusão não. Ela vale para Cloud Run **service** — e existe outra
primitiva, **worker pool**, feita exatamente para carga que consome fila e não atende
requisição. Eu não a conhecia, e desenhei em volta de uma limitação que não existia.

Verificado no provider que já estava instalado (`hashicorp/google` 6.50.0), antes de refazer:

| | service | worker pool |
|---|---|---|
| `ports` no container | existe | **não existe** |
| `scaling` | dentro de `template` | na **raiz** do recurso |
| `vpc_access` | `connector` ou `network_interfaces` | **só** `network_interfaces` |

A ausência de `ports` é a confirmação: não é que a porta seja opcional, é que a ideia de porta
não se aplica.

## Decisão

**O worker e o beat viram worker pools. A VM sai inteira** — com ela saem o `cloud-config`, as
unidades systemd, a regra de firewall do Redis e o `gcloud compute ssh` do workflow de deploy.

**O Redis vai para o Upstash**, externo. Com ele fora da GCP, some também o Memorystore que a
primeira versão evitava e o **conector de VPC**, que era peça paga — worker pool nem aceita
conector, e para os services o egress direto (`network_interfaces`) faz o mesmo por menos.

**A VPC fica, e por um motivo só:** fazer o `INGRESS_TRAFFIC_INTERNAL_ONLY` das duas APIs
significar alguma coisa. Foi decisão explícita de quem opera, contra a alternativa de publicar
as APIs e confiar só na autenticação da aplicação. O preço é `egress = ALL_TRAFFIC` e um Cloud
NAT — porque com a saída inteira passando pela VPC, sem NAT o Cloud Run perderia Neon, Upstash e
Anthropic de uma vez.

**O escalonamento é manual e fixo**, não automático. Para o `beat` o número é 1 por definição:
dois agendadores emitem a mesma tarefa duas vezes. Para o worker, contagem fixa é o que torna o
custo do Upstash previsível — cada instância é um laço de `BRPOP` a mais.

## Consequências

**O laço ocioso passou a ter preço, e isso é código, não infraestrutura.** No compose o Redis é
nosso e um `BRPOP` a mais não custa nada; no Upstash a conta é por comando, e um worker parado
consome cota sem nenhum trabalho ter acontecido. `broker_transport_options` no `worker.py` põe
`polling_interval` em 5s — o default de 1s dá ~86 mil comandos por dia **por instância** só para
descobrir que não há nada a fazer; 5s derrubam para ~17 mil, ao custo de, no pior caso, cinco
segundos de latência numa fila cujo trabalho mais rápido é mandar um e-mail.

O `visibility_timeout` foi a 1 h de propósito: ele precisa ser maior que a tarefa mais longa,
senão o Celery devolve para a fila algo que ainda está rodando e a tarefa executa duas vezes. A
mais longa aqui é a ingestão de documento — varredura, extração, embedding.

**Isso é uma promessa a medir, não a acreditar.** O número que decide é comando/hora com a fila
vazia, lido no painel do Upstash. Se não couber, o plano B é o Memorystore, que traz o conector
de volta — e é por isso que a medição vem antes de HML ser declarada pronta.

**Três Cloud Run Jobs passaram a existir.** `portal-migrate`, `biahflow-migrate` e
`biahflow-check` eram invocados pelos dois workflows de deploy e **não eram criados por
ninguém** — um workflow que chama recurso inexistente falha no primeiro deploy, que é tarde para
descobrir. Eles herdam o ambiente do serviço irmão em vez de repetir a lista, para não haver uma
segunda verdade sobre a mesma configuração; a exceção é o `portal-migrate`, que ganha
`DATABASE_MIGRATION_URL` porque quem escreve schema é o migrator e não o caminho de requisição
(ADR 0010).

**O que se perde ao sair da VM, e é ganho:** não há mais SO para atualizar, disco para vigiar,
nem `systemctl restart` por SSH no caminho do deploy. O módulo da VM dizia, com estas palavras,
que ela era bicho de estimação. Deixou de haver bicho.

**Fica aberto:** confirmar na execução se `gcloud run worker-pools update` já saiu de `beta`. O
Terraform marca o recurso com `launch_stage = "BETA"`, e essa linha sai quando o recurso sair de
preview.
