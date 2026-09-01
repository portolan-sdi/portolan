import assert from "node:assert/strict";
import test from "node:test";
import {
  registryEntryExists,
  registryIdFromCatalog,
  registryIdFromCatalogId,
} from "../src/lib/catalog-submission";

test("the registry id comes from the root catalog id", async () => {
  let requestedUrl = "";
  const registryId = await registryIdFromCatalog(
    "https://example.org/releases/main/catalog.json",
    async (input) => {
      requestedUrl = input.toString();
      return Response.json({
        id: "madrid-datos-abiertos",
        title: "Catálogo de Datos Abiertos del Ayuntamiento de Madrid",
      });
    },
  );

  assert.equal(requestedUrl, "https://example.org/releases/main/catalog.json");
  assert.equal(registryId, "madrid-datos-abiertos");
});

test("catalog ids become safe registry file stems", () => {
  assert.equal(registryIdFromCatalogId(" Île de France / 2026 "), "ile-de-france-2026");
});

test("a missing catalog id cannot fall back to the URL folder", async () => {
  await assert.rejects(
    registryIdFromCatalog(
      "https://example.org/releases/main/catalog.json",
      async () => Response.json({ title: "Example" }),
    ),
    /no string id/,
  );
});

test("the website detects an existing registry id before branch creation", async () => {
  let authorization = "";
  const exists = await registryEntryExists(
    "https://api.github.com/repos/portolan-sdi/portolan-registry/contents/catalogs/example.yaml?ref=main",
    "installation-token",
    async (_input, init) => {
      authorization = new Headers(init?.headers).get("Authorization") ?? "";
      return Response.json({ name: "example.yaml" });
    },
  );

  assert.equal(exists, true);
  assert.equal(authorization, "Bearer installation-token");
});

test("a missing registry id remains available", async () => {
  const exists = await registryEntryExists(
    "https://api.github.com/example.yaml",
    "installation-token",
    async () => new Response(null, { status: 404 }),
  );

  assert.equal(exists, false);
});
