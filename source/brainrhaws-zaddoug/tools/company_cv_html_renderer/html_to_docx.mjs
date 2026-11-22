#!/usr/bin/env node
import fs from "node:fs/promises";
import HtmlToDocx from "@turbodocx/html-to-docx";

const [, , inputPath, outputPath] = process.argv;

if (!inputPath || !outputPath) {
  console.error("Usage: node html_to_docx.mjs payload.json output.docx");
  process.exit(2);
}

const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
const docx = await HtmlToDocx(
  payload.html,
  payload.headerHtml || null,
  payload.documentOptions || {},
  payload.footerHtml || null,
);

await fs.writeFile(outputPath, Buffer.from(docx));
