import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Feature code never calls fetch; everything goes through @tadas/api-client.
      "no-restricted-globals": ["error", { name: "fetch", message: "use @tadas/api-client" }],
      "no-restricted-imports": [
        "error",
        { patterns: [{ group: ["**/schema", "**/schema.d"], message: "import the facade from @tadas/api-client" }] },
      ],
    },
  },
);
