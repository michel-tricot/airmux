import { defineConfig, InputTransformerFn } from "orval";
import path from "path";

const root = path.resolve(__dirname, "..", "..");
const apiClientReactSrc = path.resolve(root, "lib", "api-client-react", "src");
const apiZodSrc = path.resolve(root, "lib", "api-zod", "src");

// Our exports make assumptions about the title of the API being "Api" (i.e. generated output is `api.ts`).
// Every control plane response is `{"data": <payload>}`, so the transformer also rewrites each success
// schema to the payload it wraps and drops the envelope components. customFetch strips the `data` key at
// runtime; the two together keep the envelope out of the generated types and out of every call site.
const transformer: InputTransformerFn = (config) => {
  config.info ??= {};
  config.info.title = "Api";

  const schemas = config.components?.schemas ?? {};
  const envelopeName = (schema: unknown): string | null => {
    const ref = (schema as { $ref?: string } | undefined)?.$ref;
    const name = ref?.startsWith("#/components/schemas/") ? ref.slice("#/components/schemas/".length) : null;

    return name?.startsWith("Envelope_") ? name : null;
  };

  for (const operations of Object.values(config.paths ?? {})) {
    for (const operation of Object.values(operations ?? {})) {
      const content = (operation as any)?.responses?.["200"]?.content?.["application/json"];
      const name = envelopeName(content?.schema);
      if (name) content.schema = (schemas as any)[name].properties.data;
    }
  }

  config.components!.schemas = Object.fromEntries(
    Object.entries(schemas).filter(([name]) => !name.startsWith("Envelope_")),
  );

  return config;
};

export default defineConfig({
  "api-client-react": {
    input: {
      target: "./openapi.yaml",
      override: {
        transformer,
      },
    },
    output: {
      workspace: apiClientReactSrc,
      target: "generated",
      client: "react-query",
      mode: "split",
      clean: true,
      prettier: true,
      override: {
        fetch: {
          includeHttpResponseReturnType: false,
        },
        mutator: {
          path: path.resolve(apiClientReactSrc, "custom-fetch.ts"),
          name: "customFetch",
        },
      },
    },
  },
  zod: {
    input: {
      target: "./openapi.yaml",
      override: {
        transformer,
      },
    },
    output: {
      workspace: apiZodSrc,
      client: "zod",
      target: "generated",
      schemas: { path: "generated/types", type: "typescript" },
      mode: "split",
      clean: true,
      prettier: true,
      override: {
        zod: {
          coerce: {
            query: ['boolean', 'number', 'string'],
            param: ['boolean', 'number', 'string'],
            body: ['bigint', 'date'],
            response: ['bigint', 'date'],
          },
        },
        useDates: true,
        useBigInt: true,
      },
    },
  },
});
