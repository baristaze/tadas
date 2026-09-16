import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";
import { base } from "../../eslint.config.js";

export default tseslint.config(
  ...base,
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
