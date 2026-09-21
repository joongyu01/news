import crypto from 'node:crypto';
import {usageText} from './_usage.js';

export const DEFAULTS = {urgent:true, daily:true, mode:'standard', limit:0, watch:[], exclude:[], quiet:'off'};
export const HELP = `뉴스 봇 공통 설정 (어느 계정에서든 변경 가능)
/settings 현재 전체 설정 (/status도 가능)
/urgent_on · /urgent_off 긴급 알림
/daily_on · /daily_off 조간 알림
/mode_strict · /mode_standard 강도
/limit_5 일일 긴급 상한 (0~20, 0=제한 없음)
/quiet_22_07 · /quiet_off 휴식 시간(KST)
/watch_add_석유 · /watch_remove_석유 · /watch_list
/exclude_add_홍보 · /exclude_remove_홍보 · /exclude_list
키워드 안의 언더바는 띄어쓰기: /watch_add_석유_품질
/articles 수집 기사와 판정 · /articles_2 다음 페이지
/excluded 제외·긴급 제외 사유 · /excluded_2 다음 페이지
/usage 사용량 · /logs 운영 기록 (개인톡)
/logs_collect · /logs_alerts · /logs_dispatch
/subscribe 이 방 구독 · /unsubscribe 이 방 구독 해제
/help 도움말

설정은 모든 구독방에 공통 적용되며 응답은 요청한 방에만 보냅니다.
개인톡에서 구독 없이 설정할 수 있습니다. 기사 상세 조회는 개인톡 전용입니다.
구독/해제만 현재 방에 적용됩니다. 최대 5개 방, 키워드 각 10개.
수집 24시간 15분 간격 · AI 선별 06:00~23:30 매시 00/30분 · 조간 08:00.
관심 키워드도 업무 관련성·시급성 기준을 통과해야 발송됩니다.`;

export function globalOptions(stored) {
  return {...structuredClone(DEFAULTS), ...structuredClone(stored.global || stored.chats?.[stored.owner] || Object.values(stored.chats || {})[0] || {})};
}

export function webhookSecret() {
  const key = (process.env.SUPABASE_SERVICE_ROLE_KEY || '').trim();
  if (!key) throw new Error('Server not configured');
  return crypto.createHmac('sha256', key).update('news-bot-webhook-v1').digest('hex');
}

export function validSecret(value) {
  return crypto.timingSafeEqual(crypto.createHash('sha256').update(String(value || '')).digest(),
    crypto.createHash('sha256').update(webhookSecret()).digest());
}

export async function db(method, query='', body) {
  const url = (process.env.SUPABASE_URL || '').trim().replace(/\/$/,'');
  const key = (process.env.SUPABASE_SERVICE_ROLE_KEY || '').trim();
  if (!url || !key) throw new Error('Server not configured');
  const response = await fetch(`${url}/rest/v1/news_bot_settings?${query}`, {
    method, headers:{apikey:key, Authorization:`Bearer ${key}`, 'Content-Type':'application/json', Prefer:'return=representation'},
    signal:AbortSignal.timeout(8000), ...(body ? {body:JSON.stringify(body)} : {}),
  });
  if (!response.ok) throw new Error(`Settings HTTP ${response.status}`);
  return response.json();
}

export function command(update, stored) {
  const m = update?.message;
  if (!m || !isCommandText(m.text) || m.text.length > 500
      || !Number.isSafeInteger(update.update_id) || !Number.isSafeInteger(m.chat?.id)
      || !Number.isSafeInteger(m.from?.id) || m.forward_origin
      || !['private','group','supergroup'].includes(m.chat?.type)) return null;
  const input = /^(usage|logs)$/i.test(m.text.trim()) ? '/'+m.text.trim() : m.text.trim();
  const match = /^\/([^\s@]+)(?:@([a-z0-9_]+))?(?:\s+(.*))?$/is.exec(input);
  if (!match || (match[2] && match[2].toLowerCase() !== 'news_joongyubot')) return null;
  const parts = match[1].split('_');
  const cmd = parts.shift().toLowerCase();
  let args = (parts.length ? parts.join(' ') : match[3] || '').trim();
  if (cmd === 'quiet' && /^\d{2} \d{2}$/.test(args)) args = args.replace(' ', '-');
  if (m.from?.is_bot || m.sender_chat) return null;
  const chat = String(m.chat.id);
  const payload = structuredClone(stored);
  const known = (stored.recent || []).find(x => x.id === update.update_id);
  if (known) return {chat:m.chat.id, text:known.text};
  const options = globalOptions(payload);
  let text;
  let changed = false;
  if (cmd.toLowerCase() === 'usage') {
    text = m.chat.type !== 'private' ? '사용량은 봇과의 개인 대화에서 /usage로 확인해주세요.'
      : args ? '/usage 또는 usage만 입력해주세요.' : usageText(stored.github_usage);
  }
  else if (cmd === 'articles' || cmd === 'excluded') {
    if (m.chat.type !== 'private') text='기사 판정은 개인톡에서 /articles 또는 /excluded로 확인해주세요.';
    else if (args && !/^[1-9][0-9]{0,2}$/.test(args)) text='/articles 또는 /excluded_2 형식으로 입력해주세요.';
    else return {chat:m.chat.id, audit:{page:Number(args || 1), excluded:cmd === 'excluded'}};
  }
  else if (cmd.toLowerCase() === 'logs') {
    const selected = ({'수집':'collect','긴급':'alerts','발송':'dispatch'})[args] || args.toLowerCase();
    if (m.chat.type !== 'private') text='운영 기록은 봇과의 개인 대화에서 /logs로 확인해주세요.';
    else if (!['','collect','alerts','dispatch'].includes(selected)) text='/logs 또는 /logs_collect, /logs_alerts, /logs_dispatch를 입력해주세요.';
    else return {chat:m.chat.id, logs:selected};
  }
  else if (cmd === 'start' || cmd === 'help') text = HELP;
  else if (cmd === 'subscribe') {
    if (!payload.chats[chat] && Object.keys(payload.chats).length >= 5) text = '최대 5개 방까지 구독할 수 있습니다. 다른 방에서 /unsubscribe 후 다시 시도하세요.';
    else {
      payload.chats[chat] = structuredClone(options); changed = true;
      text = '✅ 이 방의 뉴스 구독을 연결했습니다. /status로 확인하세요.';
    }
  } else if (cmd === 'unsubscribe') {
    delete payload.chats[chat]; changed = true;
    text = '이 방의 뉴스 구독을 해제했습니다. /subscribe로 다시 연결할 수 있습니다.';
  } else if (cmd === 'status' || cmd === 'settings') {
    text = `봇 전체 공통 설정 · 구독 ${Object.keys(payload.chats).length}개 방\n모델: Gemini 3.8 Flash → 실패 시 3.7 Flash · 두 키 교대 · 하루 최대 40회\n긴급: ${options.urgent?'켜짐':'꺼짐'} · 아침 동향: ${options.daily?'켜짐':'꺼짐'}\n강도: ${options.mode} · 일일 상한: ${options.limit || '없음'}\n휴식(KST): ${options.quiet}\n관심: ${options.watch.join(', ') || '없음'}\n제외: ${options.exclude.join(', ') || '없음'}\n수집: 24시간 15분 간격 · AI 알림: 06:00~23:30 매시 00/30분 (예약 지연 가능)`;
  } else if (['urgent','daily'].includes(cmd) && ['on','off'].includes(args)) {
    options[cmd] = args === 'on'; changed = true; text = `✅ ${cmd} ${args} 전체 구독방에 적용했습니다.`;
  } else if (cmd === 'mode' && ['strict','standard'].includes(args)) {
    options.mode=args; changed=true; text=`✅ 알림 강도 ${args} 전체 구독방에 적용했습니다.`;
  } else if (cmd === 'limit' && /^(?:[0-9]|1[0-9]|20)$/.test(args)) {
    options.limit=Number(args); changed=true; text=`✅ 긴급 알림 하루 ${Number(args) || '제한 없음'}${Number(args)?'건':''} 전체 구독방에 적용했습니다.`;
  } else if (cmd === 'quiet' && (args === 'off' || /^(?:[01][0-9]|2[0-3])-(?:[01][0-9]|2[0-3])$/.test(args))) {
    if (args !== 'off' && args.slice(0,2) === args.slice(3)) text='시작과 종료 시각을 다르게 입력하세요.';
    else {options.quiet=args; changed=true; text=`✅ 긴급 알림 휴식 시간 ${args} (KST) 전체 구독방에 적용했습니다.`;}
  } else if (['watch','exclude'].includes(cmd)) {
    const [op, ...parts] = args.split(/\s+/); const word=parts.join(' ').trim();
    if (op === 'list') text = `${cmd}: ${options[cmd].join(', ') || '없음'}`;
    else if (!['add','remove'].includes(op) || !word || word.length>30 || /[\r\n]/.test(word)) text=`/${cmd}_add_키워드 또는 /${cmd}_remove_키워드 (1~30자)`;
    else if (op === 'add' && options[cmd].length>=10 && !options[cmd].includes(word)) text='키워드는 종류별 최대 10개입니다.';
    else {
      options[cmd] = op==='add' ? [...new Set([...options[cmd],word])] : options[cmd].filter(x=>x!==word);
      changed=true; text=`✅ ${cmd}: ${options[cmd].join(', ') || '없음'}`;
    }
  } else text='명령 형식을 확인해주세요. /help로 사용법을 볼 수 있습니다.';
  if (changed) {
    payload.global = options;
    for (const id of Object.keys(payload.chats)) payload.chats[id] = structuredClone(options);
  }
  if (changed) payload.recent=[...(payload.recent || []),{id:update.update_id,text}].slice(-30);
  return {chat:m.chat.id, text, ...(changed?{payload}: {})};
}

export function isCommandText(text) {
  return typeof text === 'string' && (text.startsWith('/') || /^(usage|logs)$/i.test(text.trim()));
}
