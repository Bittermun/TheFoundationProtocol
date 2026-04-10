# Deploy the TFP Demo Node

## Local (recommended first)

```bash
cd /home/runner/work/Scholo/Scholo
docker compose up --build
```

## Render one-click template

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Bittermun/Scholo)

## Railway one-click template

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/Bittermun/Scholo)

> After deployment, set start command to:
>
> `uvicorn tfp_demo.server:app --host 0.0.0.0 --port $PORT`
