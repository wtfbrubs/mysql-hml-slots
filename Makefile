include .env
export

.PHONY: up-prd down-prd up-base down-base refresh snapshot \
        create-slot destroy-slot list expire help

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
	@echo ""
