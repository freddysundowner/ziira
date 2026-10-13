import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "src/api/schema.d.ts"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: reactHooks.configs.recommended.rules,
  },
  {
    // Module boundaries, like import-linter on the backend: a module may import only the SDK,
    // its own files (relative paths) and other modules' public.ts.
    files: ["src/modules/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": ["error", {
        patterns: [
          { group: ["@/shell", "@/shell/*", "@/api/*", "@/sdk/*"], message: "Modules import only from @/sdk." },
          { group: ["@/modules/*/*", "!@/modules/*/public"], message: "Import another module only through its public.ts." },
          { group: ["../../*"], message: "Stay inside your module; use @/sdk or @/modules/<name>/public." },
        ],
      }],
    },
  },
);
