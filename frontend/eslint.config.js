import js from "@eslint/js";
import ts from "typescript-eslint";
export default ts.config(js.configs.recommended, ...ts.configs.recommended, {
  files: ["src/**/*.{ts,tsx}"],
  languageOptions: {
    globals: {
      window: "readonly",
      document: "readonly",
      fetch: "readonly",
      File: "readonly",
      FormData: "readonly",
      AbortController: "readonly",
      DOMException: "readonly",
      setTimeout: "readonly",
      clearTimeout: "readonly",
      URL: "readonly",
      RequestInit: "readonly",
    },
  },
});
