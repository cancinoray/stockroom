#!/usr/bin/env node
// Compare FastAPI's generated OpenAPI document with the frozen openapi.yaml.
// Only the structural contract is compared: paths, operations, status codes,
// parameters, request bodies, required fields, enum values and schemas.
// Descriptions, examples, summaries and titles are documentation, not contract.

import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, '..', '..');
const CONTRACT_PATH = path.join(REPO_ROOT, 'openapi.yaml');

const FASTAPI_DOCUMENT = `
import json
from backend.main import create_app

print(json.dumps(create_app().openapi()))
`;

const CONTRACT_DOCUMENT = `
import json
import pathlib
import yaml

print(json.dumps(yaml.safe_load(pathlib.Path("openapi.yaml").read_text())))
`;

const METHODS = ['get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'];

function runPython(script) {
  return execFileSync('uv', ['run', 'python', '-c', script], {
    cwd: REPO_ROOT,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
}

function refName(ref) {
  return typeof ref === 'string' ? (ref.split('/').pop() ?? ref) : ref;
}

function isObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function sorted(value) {
  return [...value].sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
}

function projectSchema(schema) {
  if (!isObject(schema)) {
    return schema;
  }

  const out = {};

  if (schema.$ref) out.$ref = refName(schema.$ref);
  if (schema.type !== undefined) out.type = schema.type;
  if (schema.format !== undefined) out.format = schema.format;
  if (schema.nullable !== undefined) out.nullable = schema.nullable;
  if (schema.enum !== undefined) out.enum = sorted(schema.enum);
  if (schema.required !== undefined) out.required = sorted(schema.required);
  if (schema.minimum !== undefined) out.minimum = schema.minimum;
  if (schema.maximum !== undefined) out.maximum = schema.maximum;
  if (schema.minLength !== undefined) out.minLength = schema.minLength;
  if (schema.maxLength !== undefined) out.maxLength = schema.maxLength;
  if (schema.minItems !== undefined) out.minItems = schema.minItems;
  if (schema.items !== undefined) out.items = projectSchema(schema.items);
  if (schema.not !== undefined) out.not = projectSchema(schema.not);

  for (const keyword of ['oneOf', 'anyOf', 'allOf']) {
    if (schema[keyword] !== undefined) {
      out[keyword] = sorted(schema[keyword].map(projectSchema));
    }
  }

  if (schema.properties !== undefined) {
    out.properties = Object.fromEntries(
      Object.entries(schema.properties).map(([name, property]) => [
        name,
        projectSchema(property),
      ]),
    );
  }

  return out;
}

function projectContent(content) {
  if (!isObject(content)) {
    return null;
  }

  return Object.fromEntries(
    Object.entries(content).map(([mediaType, media]) => [
      mediaType,
      { schema: projectSchema(media?.schema) },
    ]),
  );
}

function projectParameter(parameter) {
  if (parameter?.$ref) {
    return { $ref: refName(parameter.$ref) };
  }

  return {
    in: parameter?.in ?? null,
    required: Boolean(parameter?.required),
    schema: projectSchema(parameter?.schema),
  };
}

function projectOperation(operation) {
  const responses = Object.fromEntries(
    Object.entries(operation?.responses ?? {})
      .filter(([status]) => status !== 'default')
      .map(([status, response]) => [
        status,
        {
          $ref: response?.$ref ? refName(response.$ref) : null,
          content: projectContent(response?.content),
        },
      ]),
  );

  return {
    parameters: sorted((operation?.parameters ?? []).map(projectParameter)),
    requestBody: operation?.requestBody
      ? {
          required: Boolean(operation.requestBody.required),
          content: projectContent(operation.requestBody.content),
        }
      : null,
    responses,
  };
}

function project(document) {
  const paths = {};

  for (const [pathname, item] of Object.entries(document?.paths ?? {})) {
    const operations = {};

    for (const method of METHODS) {
      if (item?.[method]) {
        operations[method] = projectOperation(item[method]);
      }
    }

    paths[pathname] = operations;
  }

  const schemas = Object.fromEntries(
    Object.entries(document?.components?.schemas ?? {}).map(([name, schema]) => [
      name,
      projectSchema(schema),
    ]),
  );

  return { paths, schemas };
}

function format(value) {
  return JSON.stringify(value);
}

function diff(expected, actual, location, differences) {
  if (JSON.stringify(expected) === JSON.stringify(actual)) {
    return differences;
  }

  if (!isObject(expected) || !isObject(actual)) {
    differences.push(
      `${location}: contract has ${format(expected)}, FastAPI has ${format(actual)}`,
    );
    return differences;
  }

  const keys = new Set([...Object.keys(expected), ...Object.keys(actual)]);

  for (const key of [...keys].sort()) {
    const next = `${location}/${key}`;

    if (!(key in actual)) {
      differences.push(`${next}: missing from FastAPI (contract has ${format(expected[key])})`);
    } else if (!(key in expected)) {
      differences.push(`${next}: only in FastAPI (${format(actual[key])})`);
    } else {
      diff(expected[key], actual[key], next, differences);
    }
  }

  return differences;
}

function main() {
  let fastapi;
  let contract;

  try {
    fastapi = JSON.parse(runPython(FASTAPI_DOCUMENT));
  } catch (error) {
    console.error('check:contract — could not generate the FastAPI document with uv run python.');
    console.error(error?.stderr?.toString?.() || error?.message || error);
    process.exit(2);
  }

  try {
    contract = JSON.parse(runPython(CONTRACT_DOCUMENT));
  } catch (error) {
    console.error(`check:contract — could not parse ${CONTRACT_PATH}.`);
    console.error(error?.stderr?.toString?.() || error?.message || error);
    process.exit(2);
  }

  const differences = diff(project(contract), project(fastapi), '', []);

  if (differences.length === 0) {
    console.log('check:contract — FastAPI matches openapi.yaml.');
    return;
  }

  const limit = 160;
  console.error('check:contract — contract drift detected.');
  console.error(
    `The FastAPI document and openapi.yaml disagree in ${differences.length} place(s):`,
  );

  for (const line of differences.slice(0, limit)) {
    console.error(`  ${line}`);
  }

  if (differences.length > limit) {
    console.error(`  … and ${differences.length - limit} more.`);
  }

  process.exit(1);
}

main();
