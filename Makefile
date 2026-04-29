include .env
export

.PHONY: up-prd down-prd up-base down-base refresh snapshot \
        create-slot destroy-slot list expire \
        setup-replication replication-status \
        agent dashboard \
        agent-build agent-up agent-down \
        dashboard-build dashboard-up dashboard-down \
        github-labels help

up-prd:
	cd docker/prd && docker compose up -d

down-prd:
	cd docker/prd && docker compose down

up-base:
	cd docker/base && docker compose up -d

down-base:
	cd docker/base && docker compose down

refresh:
	./scripts/refresh_base.sh

snapshot:
	./scripts/snapshot.sh

create-slot:
	./scripts/create_slot.sh $(name) $(owner) $(ttl)

destroy-slot:
	./scripts/destroy_slot.sh $(name)

list:
	./scripts/list_slots.sh

expire:
	./scripts/expire_slots.sh

setup-replication:
	./scripts/setup_replication.sh

replication-status:
	@docker exec mysql-hml-base mysql -uroot -p"$$BASE_MYSQL_ROOT_PASSWORD" 2>/dev/null -e "SHOW REPLICA STATUS\G" | \
	  grep -E "(Replica_IO_Running|Replica_SQL_Running|Seconds_Behind|Last_Error|Source_Host|Source_Port)"

# ── Agente local (sem Docker) ────────────────────────────────────────────────
agent:
	python3 agent.py

# ── Dashboard local (sem Docker) ─────────────────────────────────────────────
dashboard:
	python3 dashboard.py

# ── Docker: agente por servidor ──────────────────────────────────────────────
agent-build:
	docker build -t mysql-hml-agent:latest .

agent-up: agent-build
	PROJECT_ROOT="$(CURDIR)" docker compose -f docker-compose.agent.yml up -d
	@echo "Agent disponível em http://localhost:$${AGENT_PORT:-8766}"

agent-down:
	docker compose -f docker-compose.agent.yml down

# ── Docker: dashboard central ─────────────────────────────────────────────────
dashboard-build:
	docker build -t mysql-hml-dashboard:latest .

dashboard-up: dashboard-build
	docker compose -f docker-compose.dashboard.yml up -d
	@echo "Dashboard disponível em http://localhost:$${DASHBOARD_PORT:-8080}"

dashboard-down:
	docker compose -f docker-compose.dashboard.yml down

# Cria labels hml-01..hml-NN no repositório GitHub (requer gh CLI autenticado)
github-labels:
	@for i in $$(seq 1 $${n:-10}); do \
	  LABEL=$$(printf "hml-%02d" $$i); \
	  gh label create "$$LABEL" --color "0075ca" --description "Slot HML $$i" --force && \
	  echo "  label criada: $$LABEL" || true; \
	done

help:
	@echo ""
	@echo "  up-prd                                   Sobe MySQL simulado de PRD (local)"
	@echo "  down-prd                                 Para o MySQL PRD local"
	@echo "  up-base                                  Sobe o MySQL HML base"
	@echo "  down-base                                Para o MySQL HML base"
	@echo "  refresh                                  Copia dados do PRD para o base + snapshot"
	@echo "  snapshot                                 Gera snapshot do base (sem refresh)"
	@echo "  create-slot name=X [owner=Y] [ttl=Z]     Cria slot"
	@echo "  destroy-slot name=X                      Destrói slot"
	@echo "  list                                     Lista slots com status de expiração"
	@echo "  expire                                   Destrói todos os slots expirados"
	@echo "  setup-replication                        Configura replicação PRD→base"
	@echo "  replication-status                       Mostra status da replicação do base"
	@echo "  agent                                    Sobe agente local (porta 8766)"
	@echo "  dashboard                                Sobe dashboard local (porta 8080)"
	@echo "  agent-up                                 Sobe agente em Docker"
	@echo "  agent-down                               Para agente Docker"
	@echo "  dashboard-up                             Sobe dashboard central em Docker"
	@echo "  dashboard-down                           Para dashboard Docker"
	@echo "  github-labels [n=10]                     Cria labels hml-01..hml-NN no GitHub"
	@echo ""
