# Website für die Getränkeliste

Dieses Repository beinhaltet den Quellcode für die Website der Getränkeliste.

Nach Problemen mit der Prepaid-Liste wird hier ein neuer Versuch gestartet, diese Liste ins digitale umzuwandeln.

## Development

Bereits integriert ist eine bile-based Datenbank basierend auf noSQL. Die Website wird gebaut mithilfe von uvicorn und FastAPI.

Zum entwickeln und testen bietet uvicorn eine hot-reload Funktionalität an, das heißt ein neustarten des Services ist
auch nach Änderungen im Code nicht erforderlich.

```shell
uvicorn main:app --reload
```

In Produktion kann der Service ohne reload, aber mit mehr workers gestartet werden. Hier werden zusätzlich der Host
festgelegt und Flags für den Reverse Proxy gesetzt, welcher in der IP-Range `172.16.0.0/12` liegt.

```shell
uvicorn --host "172.17.1.108" --port 8000 --workers 4 --proxy-headers --forwarded-allow-ips "172.16.0.0/12" main:app
```
