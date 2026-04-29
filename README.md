# mysql-hml-slots

[![Slot PR](https://github.com/wtfbrubs/mysql-hml-slots/actions/workflows/slot-pr.yml/badge.svg)](https://github.com/wtfbrubs/mysql-hml-slots/actions/workflows/slot-pr.yml)
[![Slot Manage](https://github.com/wtfbrubs/mysql-hml-slots/actions/workflows/slot-manage.yml/badge.svg)](https://github.com/wtfbrubs/mysql-hml-slots/actions/workflows/slot-manage.yml)
[![Slot Expire](https://github.com/wtfbrubs/mysql-hml-slots/actions/workflows/slot-expire.yml/badge.svg)](https://github.com/wtfbrubs/mysql-hml-slots/actions/workflows/slot-expire.yml)
![MySQL](https://img.shields.io/badge/MySQL-8.4-blue?logo=mysql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

Solução automatizada para replicar um banco MySQL de Produção para um ambiente de Homologação (HML) com suporte a múltiplos **slots** isolados — cada slot é uma instância MySQL efêmera com TTL configurável, criada em segundos via Clone Plugin.

## Arquitetura

```
PRD (RDS MySQL / container local)
        │
        │  Replicação GTID nativa (binlog)
        ▼
 mysql-hml-base  (container Docker — réplica read-only)
        │
        │  MySQL Clone Plugin (segundos) ou snapshot fallback
        ▼
 ┌──────────────────────────────────────┐
 │  Slots (containers efêmeros)         │
 │                                      │
 │  hml-01  :3310  TTL 24h             │
 │  hml-02  :3311  TTL 24h             │
 │  hml-03  :3312  TTL 24h             │
 └──────────────────────────────────────┘
        │
        │  Agente JSON API por servidor (agent.py :8766)
        ▼
 Dashboard Central (dashboard.py :8080)
 ← agrega N servidores em paralelo →
```

Cada slot:
- É criado via **Clone Plugin** (O(minutos) mesmo em 1 TB) com fallback para snapshot (mysqldump)
- Tem seu próprio diretório de dados (`data/slots/<name>/`)
- Tem `server-id` único (derivado da porta)
- É destruído automaticamente ao expirar o TTL
- Faz rollback automático se a criação falhar em qualquer etapa

---

## Pré-requisitos

| Ferramenta | Versão mínima |
|---|---|
| Docker + Compose plugin | 24+ / v2 |
| `jq` | 1.6+ |
| Python | 3.10+ (stdlib, sem dependências extras) |
| `flock`, `ss`, `envsubst`, `zcat` | padrão Linux |

```bash
# Ubuntu/Debian
sudo apt-get install -y jq python3

# Amazon Linux 2
sudo yum install -y jq python3 mysql
```

---

## Uso local (simulação completa PRD → HML)

### 1. Subir PRD simulado e base

```bash
make up-prd     # MySQL PRD na porta 3307
make up-base    # MySQL HML base na porta 3306
```

### 2. Configurar replicação PRD → base (recomendado)

```bash
make setup-replication
```

Cria usuário de replicação no PRD, usuário Clone Plugin no base, inicia replicação GTID. Executa uma vez; a replicação é persistente.

Verificar status:

```bash
make replication-status
```

### 3. Popular o PRD com dados de teste (opcional)

```bash
mysql -h 127.0.0.1 -P 3307 -uroot -pprd-root123 <<'SQL'
CREATE DATABASE loja;
USE loja;
CREATE TABLE produtos (id INT AUTO_INCREMENT PRIMARY KEY, nome VARCHAR(100));
INSERT INTO produtos (nome) VALUES ('Teclado'), ('Monitor'), ('Mouse');
SQL
```

### 4. Ciclo completo: refresh + snapshot

Necessário apenas se **não** usar replicação nativa:

```bash
make refresh    # copia PRD → base via mysqldump + gera snapshot
```

Ou apenas snapshot do estado atual do base:

```bash
make snapshot
```

### 5. Criar slots

```bash
make create-slot name=hml-01 owner=bruno ttl=24
make create-slot name=hml-02 owner=alice ttl=24
```

Se o Clone Plugin estiver ativo, cada slot é criado em segundos clonando diretamente do base. Caso contrário usa o último `snapshots/latest.sql.gz`.

### 6. Conectar ao slot

```bash
mysql -h 127.0.0.1 -P 3310 -uroot -proot123   # hml-01
mysql -h 127.0.0.1 -P 3311 -uroot -proot123   # hml-02
```

### 7. Listar, destruir e expirar

```bash
make list
make destroy-slot name=hml-01
make expire
```

---

## Dashboard

Interface web para monitorar todos os slots, replicação e containers em tempo real.

### Subir localmente

```bash
# Terminal 1 — agente que coleta dados deste servidor
python3 agent.py

# Terminal 2 — dashboard central apontando para o agente
AGENTS="BRUNO-PC=http://localhost:8766" python3 dashboard.py
```

Abrir em: **http://localhost:8080**

Ou via Makefile:

```bash
make agent      # porta 8766
make dashboard  # porta 8080  (requer AGENTS no ambiente)
```

### Multi-servidor (Docker / Portainer)

**Em cada servidor HML** — implantar `docker-compose.agent.yml`:

```bash
PROJECT_ROOT=/home/ubuntu/mysql-hml-slots \
SERVER_NAME=servidor-01 \
docker compose -f docker-compose.agent.yml up -d
```

Ou via Makefile:

```bash
make agent-up    # usa PROJECT_ROOT=$(CURDIR) e SERVER_NAME do hostname
make agent-down
```

**No servidor do dashboard central** — implantar `docker-compose.dashboard.yml`:

```bash
AGENTS="servidor-01=http://192.168.1.10:8766,servidor-02=http://192.168.1.11:8766" \
docker compose -f docker-compose.dashboard.yml up -d
```

Ou montar `agents.json` (copie de `agents.json.example`):

```bash
AGENTS_CONFIG=/etc/hml/agents.json \
docker compose -f docker-compose.dashboard.yml up -d
```

Ou via Makefile:

```bash
make dashboard-up
make dashboard-down
```

### Endpoints do agente (`:8766`)

| Endpoint | Método | Descrição |
|---|---|---|
| `/health` | GET | Status do agente |
| `/api` | GET | Dados completos: slots, base, prd, replicação, snapshot |
| `/logs?slot=hml-01` | GET | Últimas 100 linhas de log do container |
| `/action/refresh` | POST | Reinicia replicação do base (`STOP/START REPLICA`) |
| `/action/restart` | POST `{"slot":"hml-01"}` | Reinicia container do slot |
| `/action/status?job_id=X` | GET | Status de job em background |

### Funcionalidades do dashboard

- Cards globais: servidores online, total de slots, expirando em breve, erros de replicação
- Seção por servidor: status do base e PRD, métricas de replicação (IO/SQL thread, lag, GTID)
- Tabela de slots: status, TTL restante, dono, CPU/mem, queries, alertas de expiração
- Ações: reiniciar slot, voltar replicação do base, ver logs em modal
- Atualização automática a cada 30 segundos

---

## Referência de comandos

| Comando | Descrição |
|---|---|
| `make up-prd` | Sobe MySQL PRD local (porta 3307) |
| `make down-prd` | Para o MySQL PRD local |
| `make up-base` | Sobe MySQL HML base (porta 3306) |
| `make down-base` | Para o MySQL HML base |
| `make setup-replication` | Configura replicação GTID nativa PRD → base |
| `make replication-status` | Mostra status da replicação do base |
| `make refresh` | Copia PRD → base via mysqldump + snapshot |
| `make snapshot` | Gera snapshot do base sem refresh |
| `make create-slot name=X [owner=Y] [ttl=Z]` | Cria slot (Clone Plugin ou snapshot) |
| `make destroy-slot name=X` | Destrói slot e remove dados |
| `make list` | Lista slots com status de expiração |
| `make expire` | Destrói slots com TTL expirado |
| `make agent` | Sobe agente local (porta 8766) |
| `make dashboard` | Sobe dashboard local (porta 8080) |
| `make agent-up` | Sobe agente em Docker |
| `make agent-down` | Para agente Docker |
| `make dashboard-up` | Sobe dashboard central em Docker |
| `make dashboard-down` | Para dashboard Docker |
| `make github-labels [n=10]` | Cria labels hml-01..hml-NN no GitHub |

### Variáveis do `create-slot`

| Variável | Padrão | Descrição |
|---|---|---|
| `name` | *(obrigatório)* | Nome do slot — padrão `hml-NN` (ex: `hml-01`) |
| `owner` | `unknown` | Responsável pelo slot |
| `ttl` | `24` | Tempo de vida em horas |

### Padrão de nomenclatura e portas

O padrão adotado é `hml-NN`, onde `NN` é um número sequencial por ambiente/desenvolvedor. A porta é **determinística** — derivada do sufixo numérico — garantindo string de conexão fixa independente de destroy/recreate:

| Slot | Porta |
|---|---|
| `hml-01` | `3310` |
| `hml-02` | `3311` |
| `hml-NN` | `3309 + N` |

---

## Configuração (`.env`)

```bash
# Base HML
BASE_MYSQL_PORT=3306
BASE_MYSQL_ROOT_PASSWORD=root123
MYSQL_VERSION=8.4
SLOTS_BASE_PORT=3310
SNAPSHOT_DIR=snapshots

# PRD local (simulação)
PRD_MYSQL_ROOT_PASSWORD=prd-root123
PRD_MYSQL_PORT=3307
PRD_MODE=docker             # docker | remote

# PRD remoto (RDS / HeatWave) — ativar com PRD_MODE=remote
# PRD_HOST=endpoint.region.rds.amazonaws.com
# PRD_PORT=3306
# PRD_USER=admin
# PRD_MYSQL_ROOT_PASSWORD=<senha>

# Replicação nativa (make setup-replication)
REPLICATION_USER=hml_repl
REPLICATION_PASSWORD=repl-secret-change-me

# Clone Plugin para criação de slots rápida
CLONE_USER=hml_clone
CLONE_PASSWORD=clone-secret-change-me

# Lag máximo aceitável antes de tirar snapshot (segundos)
MAX_LAG_SECONDS=30
```

---

## Estrutura do projeto

```
mysql-hml-slots/
├── agent.py                    # API JSON por servidor (porta 8766)
├── dashboard.py                # Dashboard central multi-servidor (porta 8080)
├── Dockerfile                  # Imagem única para agent e dashboard
├── docker-compose.agent.yml    # Stack Portainer por servidor
├── docker-compose.dashboard.yml # Stack do dashboard central
├── agents.json.example         # Exemplo de config multi-servidor
├── docker/
│   ├── base/                   # MySQL HML base (my.cnf + compose)
│   ├── prd/                    # MySQL PRD simulado
│   └── slot/                   # Template docker-compose para slots
├── scripts/
│   ├── common.sh               # Funções compartilhadas (log, lock, wait_for_mysql)
│   ├── setup_replication.sh    # Bootstrap replicação GTID PRD → base
│   ├── refresh_base.sh         # Sincroniza base + snapshot (detecta replicação)
│   ├── snapshot.sh             # Gera snapshot do base
│   ├── create_slot.sh          # Cria slot (Clone Plugin ou snapshot + rollback)
│   ├── destroy_slot.sh         # Destroi slot e limpa dados
│   ├── expire_slots.sh         # Remove slots com TTL expirado
│   ├── list_slots.sh           # Lista slots com status
│   └── next_port.sh            # Porta determinística por sufixo numérico
├── registry/
│   └── slots.json              # Estado dos slots ativos
├── snapshots/                  # Dumps comprimidos (gerado, ignorado pelo git)
├── data/                       # Dados dos containers (gerado, ignorado pelo git)
├── terraform/                  # Infraestrutura cloud (AWS)
└── .github/workflows/          # CI/CD para gerenciar slots remotamente
```

---

## Cloud (AWS)

### Infraestrutura provisionada pelo Terraform

| Recurso | Descrição |
|---|---|
| VPC + subnets | Rede isolada com subnets públicas e privadas |
| RDS MySQL 8.0 | Instância PRD em subnet privada, binlog habilitado |
| EC2 (t3.small) | Host HML com Docker, cron de expiração, EIP fixo |
| IAM role (EC2) | Permissão SSM para acesso via GitHub Actions sem porta 22 |
| IAM user (CI/CD) | Credenciais mínimas para `ssm:SendCommand` |

### Deploy

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# editar terraform.tfvars com seus valores

terraform init
terraform plan
terraform apply
```

### Outputs após o apply

```bash
terraform output hml_host_ssh          # ssh ec2-user@<ip>
terraform output hml_instance_id       # adicionar como HML_INSTANCE_ID no GitHub
terraform output rds_prd_endpoint      # endpoint do RDS
terraform output github_actions_access_key_id
terraform output -raw github_actions_secret_access_key
```

### Secrets necessários no GitHub

| Secret | Valor |
|---|---|
| `AWS_ACCESS_KEY_ID` | output `github_actions_access_key_id` |
| `AWS_SECRET_ACCESS_KEY` | output `github_actions_secret_access_key` |
| `AWS_REGION` | região usada no terraform (ex: `us-east-1`) |
| `HML_INSTANCE_ID` | output `hml_instance_id` |

---

## GitHub Actions

### Slot por PR (fluxo recomendado)

Cada desenvolvedor tem um slot fixo (`hml-01`, `hml-02`, ...). Para subir o ambiente de uma feature:

1. Crie as labels no repositório (uma vez):
   ```bash
   make github-labels        # cria hml-01 a hml-10
   make github-labels n=5    # cria hml-01 a hml-05
   ```

2. Abra um PR e adicione a label `hml-01` (ou o seu slot):

   ```
   PR #42 — feat: novo checkout
   Labels: hml-01
   ```

3. O workflow cria o slot automaticamente e comenta no PR:

   ```
   ## Slot HML criado — hml-01

   | Slot    | hml-01              |
   | Branch  | feat/novo-checkout  |
   | Host    | hml.suaempresa.com  |
   | Porta   | 3310                |
   | Usuário | root                |
   | TTL     | 72h                 |

   mysql -h hml.suaempresa.com -P 3310 -uroot -p<senha>

   > Remova a label `hml-01` ou feche o PR para destruir o ambiente.
   ```

4. Ao mergear ou fechar o PR, o slot é destruído automaticamente.

### Gerenciar slots manualmente

`Actions → HML Slots — Gerenciar → Run workflow`

| Input | Opções |
|---|---|
| `action` | `create` / `destroy` / `list` / `expire` / `refresh` / `snapshot` |
| `slot_name` | nome do slot (obrigatório para create/destroy) |
| `owner` | responsável (padrão: `github-actions`) |
| `ttl` | horas de vida (padrão: `24`) |

### Expiração agendada

`HML Slots — Expirar` roda automaticamente todo dia à 01:00 UTC e pode ser acionado manualmente.

### Runner local (self-hosted)

Para testar pipelines sem AWS, configure um runner self-hosted:

```bash
# Baixar e configurar
mkdir actions-runner && cd actions-runner
curl -o actions-runner-linux-x64.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.322.0/actions-runner-linux-x64-2.322.0.tar.gz
tar xzf actions-runner-linux-x64.tar.gz
./config.sh --url https://github.com/<org>/<repo> --token <TOKEN>
./run.sh
```

Com o runner ativo, use o workflow `slot-local.yml` que roda `make` diretamente no projeto sem checkout nem AWS.
