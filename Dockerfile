FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      docker.io \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY agent.py dashboard.py ./

EXPOSE 8766 8080

# Override CMD per service in docker-compose:
#   agent:     python3 agent.py
#   dashboard: python3 dashboard.py
CMD ["python3", "agent.py"]
