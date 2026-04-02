# Assistente Médico IA — Frontend

Interface web em **React** para o protótipo do Assistente Médico IA: painel com **navegação lateral**, **barra superior** com dados do paciente, **busca de paciente** (mock) e **painel de alertas** (mock). Os textos da interface estão em **português (pt-BR)**.

Contrato REST esperado para integração futura: veja **[API_ASSUMPTIONS.md](./API_ASSUMPTIONS.md)**.

## Requisitos

- **Node.js 22** (conforme `engines` em `package.json`)

## Desenvolvimento

```bash
cd frontend
npm install
npm run dev
```

Abra o endereço exibido no terminal (por padrão `http://localhost:5173`).

## Build de produção

```bash
npm run build
npm run preview
```

## Docker

Construir a imagem a partir da raiz do repositório ou da pasta `frontend`:

```bash
docker build -t assistente-medico-ui ./frontend
```

Executar (porta **8080** no host → **80** no container):

```bash
docker run --rm -p 8080:80 assistente-medico-ui
```

Acesse `http://localhost:8080`. A configuração **nginx** faz fallback para `index.html` (SPA).

### Variáveis de ambiente (futuro)

Quando houver API real, defina no build, por exemplo:

```bash
docker build --build-arg VITE_API_BASE_URL=https://api.exemplo.com -t assistente-medico-ui ./frontend
```

*(Requer ajuste no `Dockerfile` para repassar `ARG` ao `npm run build`, se necessário.)*

## Estrutura principal

- `src/layouts/AppLayout.tsx` — shell (sidebar + barra + conteúdo)
- `src/components/` — barra superior, busca, alertas, badge de internação
- `src/api/mockApi.ts` — atraso simulado e dados fictícios
- `src/lib/checkInStatus.ts` — regra de 12 horas para o indicador

## Scripts npm

| Script    | Descrição                          |
| --------- | ---------------------------------- |
| `npm run dev`     | Servidor de desenvolvimento Vite   |
| `npm run build`   | `tsc` + build otimizado            |
| `npm run preview` | Servir pasta `dist` localmente     |
