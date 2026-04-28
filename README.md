# mysql-hml-slots

Solução automatizada para replicar um banco MySQL de Produção para um ambiente de Homologação (HML) com suporte a múltiplos **slots** isolados — cada slot é uma instância MySQL efêmera, restaurada a partir de um snapshot do PRD, com TTL configurável.

## Arquitetura

```
PRD (RDS MySQL / container local)
        │
        │  refresh_base.sh  (mysqldump)
        ▼
 mysql-hml-base  (container Docker)
        │
        │  snapshot.sh  →  snapshots/latest.sql.gz
        ▼
 ┌──────────────────────────────────────┐
 │  Slots (containers efêmeros)         │
 │                                      │
 │  hml-01  :3310  TTL 24h             │
 │  hml-02  :3311  TTL 24h             │
 │  hml-03  :3312  TTL 24h             │
 └──────────────────────────────────────┘
```

Cada slot:
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
| `flock`, `ss`, `envsubst`, `zcat` | padrão Linux |

```bash
# Ubuntu/Debian
sudo apt-get install -y jq

# Amazon Linux 2 (cloud)
sudo yum install -y jq mysql
```

---

## Uso local (simulação completa PRD → HML)

### 1. Subir PRD simulado e base

```bash
make up-prd     # MySQL PRD na porta 3307
make up-base    # MySQL HML base na porta 3306
```

### 2. Popular o PRD com dados de teste (opcional)

```bash
mysql -h 127.0.0.1 -P 3307 -uroot -pprd-root123 <<'SQL'
CREATE DATABASE loja;
USE loja;
CREATE TABLE produtos (id INT AUTO_INCREMENT PRIMARY KEY, nome VARCHAR(100));
INSERT INTO produtos (nome) VALUES ('Teclado'), ('Monitor'), ('Mouse');
SQL
```

### 3. Ciclo completo: refresh + snapshot + slot

```bash
make refresh    # copia PRD → base + gera snapshot automaticamente
```

Ou em passos separados:

```bash
make snapshot   # apenas gera snapshot do estado atual do base
```

### 4. Criar slots

```bash
make create-slot name=hml-01 owner=bruno ttl=24
make create-slot name=hml-02 owner=alice ttl=24
```

### 5. Conectar ao slot

```bash
mysql -h 127.0.0.1 -P 3310 -uroot -proot123   # hml-01
mysql -h 127.0.0.1 -P 3311 -uroot -proot123   # hml-02
```

### 6. Listar slots

```bash
make list
```

```
SLOT                   OWNER           PORTA  STATUS     CRIADO EM                  EXPIRA EM
----                   -----           -----  ------     ---------                  ---------
hml-01                 bruno           3310   running    2026-04-28T10:00:00-03:00  2026-04-29T10:00:00-03:00
hml-02                 alice           3311   running    2026-04-28T10:05:00-03:00  2026-04-29T10:05:00-03:00
```

### 7. Destruir slot

```bash
make destroy-slot name=feat-login
```

### 8. Destruir slots expirados

```bash
make expire
```

---

## Referência de comandos

| Comando | Descrição |
|---|---|
| `make up-prd` | Sobe MySQL PRD local (simulação) na porta 3307 |
| `make down-prd` | Para o MySQL PRD local |
| `make up-base` | Sobe MySQL HML base na porta 3306 |
| `make down-base` | Para o MySQL HML base |
| `make refresh` | Copia dados do PRD para o base e gera snapshot |
| `make snapshot` | Gera snapshot do base sem refresh |
| `make create-slot name=X [owner=Y] [ttl=Z]` | Cria slot restaurado do último snapshot |
| `make destroy-slot name=X` | Destrói slot e remove todos os dados |
| `make list` | Lista slots com status de expiração |
| `make expire` | Destrói todos os slots com TTL expirado |

### Variáveis do `create-slot`

| Variável | Padrão | Descrição |
|---|---|---|
| `name` | *(obrigatório)* | Nome do slot — seguir padrão `hml-NN` (ex: `hml-01`) |
| `owner` | `unknown` | Responsável pelo slot |
| `ttl` | `24` | Tempo de vida em horas |

### Padrão de nomenclatura e portas

O padrão adotado é `hml-NN`, onde `NN` é um número sequencial por ambiente/desenvolvedor. A porta é **determinística** — derivada automaticamente do sufixo numérico — garantindo string de conexão fixa independente de destroy e recreate:

| Slot | Porta |
|---|---|
| `hml-01` | `3310` |
| `hml-02` | `3311` |
| `hml-NN` | `3309 + N` |

Isso permite que cada dev configure sua string de conexão uma única vez e nunca precise alterá-la.

---

## Configuração (`.env`)

```bash
# Base HML
BASE_MYSQL_PORT=3306
BASE_MYSQL_ROOT_PASSWORD=root123
MYSQL_VERSION=8.4
SLOTS_BASE_PORT=3310        # porta inicial dos slots
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
```

---

## Estrutura do projeto

```
mysql-hml-slots/
├── docker/
│   ├── base/               # MySQL HML base
│   ├── prd/                # MySQL PRD simulado (local)
│   └── slot/               # Template para slots efêmeros
├── scripts/
│   ├── common.sh           # Funções compartilhadas (log, lock, wait_for_mysql)
│   ├── refresh_base.sh     # Copia PRD → base + snapshot
│   ├── snapshot.sh         # Gera snapshot do base
│   ├── create_slot.sh      # Cria slot com restore + rollback automático
│   ├── destroy_slot.sh     # Destroi slot e limpa dados
│   ├── expire_slots.sh     # Remove slots com TTL expirado
│   ├── list_slots.sh       # Lista slots com status
│   └── next_port.sh        # Porta determinística por sufixo (hml-01→3310) ou dinâmica
├── registry/
│   └── slots.json          # Estado dos slots ativos
├── snapshots/              # Dumps comprimidos (gerado, ignorado pelo git)
├── data/                   # Dados dos containers (gerado, ignorado pelo git)
├── terraform/              # Infraestrutura cloud (AWS)
├── .github/workflows/      # CI/CD para gerenciar slots remotamente
└── Makefile
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

---

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
