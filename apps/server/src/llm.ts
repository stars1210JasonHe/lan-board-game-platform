/**
 * LLM Provider abstraction — supports OpenClaw CLI and direct API (OpenAI-compatible).
 */

import { execFile } from 'child_process';
import { readFileSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

// ── Config ────────────────────────────────────────────────────────────────────

export interface LLMConfig {
  provider: 'openclaw' | 'openai' | 'anthropic';
  apiKey?: string;
  model?: string;
  baseUrl?: string;
}

function loadConfig(): LLMConfig {
  // Priority: env vars > config.json > default (openclaw)
  const provider = (process.env.LLM_PROVIDER || 'openclaw') as LLMConfig['provider'];
  const config: LLMConfig = {
    provider,
    apiKey: process.env.LLM_API_KEY || '',
    model: process.env.LLM_MODEL || '',
    baseUrl: process.env.LLM_BASE_URL || '',
  };

  // Try config.json
  const configPath = join(__dirname, '..', '..', '..', 'config.json');
  if (existsSync(configPath)) {
    try {
      const file = JSON.parse(readFileSync(configPath, 'utf8'));
      if (file.llm) {
        config.provider = file.llm.provider || config.provider;
        config.apiKey = file.llm.apiKey || config.apiKey;
        config.model = file.llm.model || config.model;
        config.baseUrl = file.llm.baseUrl || config.baseUrl;
      }
    } catch { /* ignore parse errors */ }
  }

  return config;
}

const config = loadConfig();
console.log(`[LLM] Provider: ${config.provider}${config.model ? ` (${config.model})` : ''}`);

// ── Skill Loading ─────────────────────────────────────────────────────────────

const skillsDir = join(__dirname, '..', '..', '..', 'skills');

function loadSkill(skillName: string): string {
  const skillPath = join(skillsDir, skillName, 'SKILL.md');
  if (!existsSync(skillPath)) return '';
  try {
    let content = readFileSync(skillPath, 'utf8');
    // Strip YAML frontmatter
    if (content.startsWith('---')) {
      const end = content.indexOf('---', 3);
      if (end !== -1) content = content.slice(end + 3).trim();
    }
    return content;
  } catch { return ''; }
}

function loadReference(skillName: string, refName: string): string {
  const refPath = join(skillsDir, skillName, 'references', refName);
  if (!existsSync(refPath)) return '';
  try {
    return readFileSync(refPath, 'utf8');
  } catch { return ''; }
}

// Pre-load skills at startup (only used by deprecated handleApiMove in index.ts)
const CHESS_SKILL = loadSkill('chess-player');
const CHESS_OPENINGS = loadReference('chess-player', 'openings.md');
const XIANGQI_SKILL = loadSkill('xiangqi-player');
const XIANGQI_OPENINGS = loadReference('xiangqi-player', 'openings.md');

console.log(`[LLM] Skills loaded: chess=${CHESS_SKILL ? 'yes' : 'no'}, xiangqi=${XIANGQI_SKILL ? 'yes' : 'no'}`);

// ── Providers ─────────────────────────────────────────────────────────────────

async function chatOpenClaw(sessionId: string, message: string, timeout: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const args = ['agent', '--session-id', sessionId, '--message', message, '--json', '--timeout', String(timeout)];
    execFile('openclaw', args, { timeout: (timeout + 5) * 1000 }, (err, stdout, stderr) => {
      if (err) { reject(new Error(stderr?.slice(0, 200) || err.message)); return; }
      try {
        const result = JSON.parse(stdout);
        const payloads = result?.result?.payloads ?? [];
        resolve(payloads[0]?.text ?? '');
      } catch {
        reject(new Error('Failed to parse openclaw response'));
      }
    });
  });
}

async function chatDirectAPI(systemPrompt: string, userMessage: string, timeout: number): Promise<string> {
  const model = config.model || (config.provider === 'anthropic' ? 'claude-sonnet-4-20250514' : 'gpt-4o');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout * 1000);

  try {
    if (config.provider === 'anthropic') {
      const baseUrl = config.baseUrl || 'https://api.anthropic.com';
      const resp = await fetch(`${baseUrl}/v1/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': config.apiKey!,
          'anthropic-version': '2023-06-01',
        },
        body: JSON.stringify({
          model,
          max_tokens: 100,
          system: systemPrompt,
          messages: [{ role: 'user', content: userMessage }],
        }),
        signal: controller.signal,
      });
      if (!resp.ok) throw new Error(`Anthropic API ${resp.status}: ${await resp.text()}`);
      const data = await resp.json() as any;
      return data.content?.[0]?.text ?? '';
    } else {
      // OpenAI-compatible (openai, together, groq, etc.)
      const baseUrl = config.baseUrl || 'https://api.openai.com';
      const resp = await fetch(`${baseUrl}/v1/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${config.apiKey}`,
        },
        body: JSON.stringify({
          model,
          max_tokens: 100,
          messages: [
            { role: 'system', content: systemPrompt },
            { role: 'user', content: userMessage },
          ],
        }),
        signal: controller.signal,
      });
      if (!resp.ok) throw new Error(`OpenAI API ${resp.status}: ${await resp.text()}`);
      const data = await resp.json() as any;
      return data.choices?.[0]?.message?.content ?? '';
    }
  } finally {
    clearTimeout(timer);
  }
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Send a chat message to the LLM.
 * For OpenClaw: systemPrompt is prepended to userMessage.
 * For direct API: systemPrompt goes in system role, userMessage in user role.
 */
export async function llmChat(
  sessionId: string,
  systemPrompt: string,
  userMessage: string,
  timeout: number = 30,
): Promise<string> {
  if (config.provider === 'openclaw') {
    // OpenClaw CLI: combine system + user into one message
    const combined = systemPrompt ? `${systemPrompt}\n\n${userMessage}` : userMessage;
    return chatOpenClaw(sessionId, combined, timeout);
  } else {
    return chatDirectAPI(systemPrompt, userMessage, timeout);
  }
}

/**
 * Get the pre-loaded skill content for a game type.
 * DEPRECATED: Only used by handleApiMove (which is no longer called by euler_play.py).
 */
export function getSkill(gameType: 'chess' | 'xiangqi'): string {
  if (gameType === 'chess') {
    return CHESS_OPENINGS ? `${CHESS_SKILL}\n\n${CHESS_OPENINGS}` : CHESS_SKILL;
  }
  return XIANGQI_OPENINGS ? `${XIANGQI_SKILL}\n\n${XIANGQI_OPENINGS}` : XIANGQI_SKILL;
}

export function getLLMProvider(): string {
  return config.provider;
}

export function getLLMModel(): string {
  return config.model || (config.provider === 'openclaw' ? 'openclaw' : 'unknown');
}
