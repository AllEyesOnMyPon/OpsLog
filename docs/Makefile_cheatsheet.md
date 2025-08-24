# start observability stack (Loki/Promtail/Prometheus/Grafana)
```
make up
```
# uruchom gateway (w innym terminalu)
```
make gateway
```

# puść sample logi (np. CSV, 50 rekordów, mniej braków)
```
make emit-csv N=50 PARTIAL=0.1
```
# inne emitery
```
make emit-json N=30 JSON_PARTIAL=0.2
make emit-noise N=40 CHAOS=0.6 SEED=123
make emit-syslog N=20 PARTIAL=0.2
make emit-minimal N=10
```
# housekeeping jednorazowo
```
make hk-once
```
# podejrzyj usługi i logi
```
make ps
make logs
```
# przeładuj Prometheusa po zmianie reguł alertów
```
make prom-reload
```
# zatrzymaj stack
```
make down
```
# (opcjonalnie) Structurizr Lite (UI na 8081) lub eksport PNG
```
make structurizr
make structurizr-export
```