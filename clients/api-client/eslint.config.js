import tseslint from "typescript-eslint";
import { base } from "../../eslint.config.js";

export default tseslint.config({ ignores: ["src/schema.d.ts"] }, ...base);
