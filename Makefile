include .env
export

.PHONY: up-prd down-prd up-base down-base refresh snapshot \
        create-slot destroy-slot list expire \
        setup-replication replication-status \
        github-labels dashboard help

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

# Cria labels hml-01..hml-NN no repositório GitHub (requer gh CLI autenticado)
# Uso: make github-labels        → cria hml-01 a hml-10
#      make github-labels n=5    → cria hml-01 a hml-05
setup-replication:
	./scripts/setup_replication.sh

replication-status:
	@docker exec mysql-hml-base mysql -uroot -p"$$BASE_MYSQL_ROOT_PASSWORD" 2>/dev/null -e "SHOW REPLICA STATUS\G" | \
	  grep -E "(Replica_IO_Running|Replica_SQL_Running|Seconds_Behind|Last_Error|Source_Host|Source_Port)"

dashboard:
	python3 dashboard.py

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
	@echo "  create-slot name=X [owner=Y] [ttl=Z]     Cria slot restaurado do último snapshot"
	@echo "  destroy-slot name=X                      Destrói slot e limpa dados"
	@echo "  list                                     Lista slots com status de expiração"
	@echo "  expire                                   Destrói todos os slots expirados"
	@echo "  github-labels [n=10]                     Cria labels hml-01..hml-NN no GitHub"
	@echo ""
