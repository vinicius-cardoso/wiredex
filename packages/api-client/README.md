# @wiredex/api-client

Typed client for the Wiredex API, shared by the web app and, later, the mobile app.

`src/generated/` is **generated. Don't edit it.** After changing an endpoint or
schema in `apps/api`, run from the repo root:

```bash
make client
```

This regenerates `src/generated/openapi.json` from the FastAPI app and
`src/generated/schema.d.ts` from that. Commit both. CI regenerates them and
fails if they differ from what's committed.

```ts
import { createApiClient } from "@wiredex/api-client";

const api = createApiClient(window.location.origin);
const { data, error } = await api.GET("/api/version");
```
