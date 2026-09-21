import crypto from 'node:crypto';
import {usageText} from './_usage.js';

export const DEFAULTS = {urgent:true, daily:true, mode:'standard', limit:0, watch:[], exclude:[], quiet:'off'};
export const HELP = `뉴스 봇 명령어 (설정은 소유자만 변경)
/status 현재 방 설정
/usage GitHub 사용량·API 잔여 한도 (개인 대화)
/logs 수집·발송 시각과 건수, 상세 로그 (개인 대화)
/subscribe 이 방 알림 구독
/unsubscribe 이 방 구독 해제
/urgent on 또는 off 긴급 알림
/daily on 또는 off 아침 동향
/mode strict 또는 standard 알림 강도
/limit 5 하루 긴급 알림 상한 (1~20, 0=제한 없음)
/quiet 22-07 또는 off 긴급 알림 휴식 시간(KST)
/watch add 키워드 관심 키워드 추가
/watch remove 키워드 제거 /watch list 목록
/exclude add 키워드 제외 키워드 추가
/exclude remove 키워드 제거 /exclude list 목록
/help 이 도움말

단톡방: 봇 초대 후 소유자가 /subscribe@news_joongyubot 전송.
방마다 별도 설정, 최대 5개 방. 관심/제외 키워드 각 10개.
관심 키워드는 수집에 반영합니다. 일반 관심 소식은 아침 분석에서 선별하고 실제 긴급 보도만 즉시 알립니다.
strict: 같은 주제 24시간 중복 억제. standard: 기존 제목 유사도 기준.
명령 응답은 즉시, 수집은 15분 간격, AI 선별은 06:00~23:30 매시 00/30분입니다.`;

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
  const match = /^\/([a-z]+)(?:@([a-z0-9_]+))?(?:\s+(.*))?$/is.exec(input);
  if (!match || (match[2] && match[2].toLowerCase() !== 'news_joongyubot')) return null;
  const [_, cmd, bot, raw=''] = match;
  const args = raw.trim();
  // Ignore third-party group commands and anonymous-admin messages entirely.
  if (String(m.from?.id) !== stored.owner || m.from?.is_bot || m.sender_chat) {
    return m.chat.type === 'private' ? {text:'이 봇은 소유자 전용입니다.', chat:m.chat.id} : null;
  }
  const chat = String(m.chat.id);
  const payload = structuredClone(stored);
  const known = (stored.recent || []).find(x => x.id === update.update_id);
  if (known) return {chat:m.chat.id, text:known.text};
  let options = payload.chats[chat];
  let text;
  let changed = false;
  if (cmd.toLowerCase() === 'usage') {
    text = m.chat.type !== 'private' ? '사용량은 봇과의 개인 대화에서 /usage로 확인해주세요.'
      : args ? '/usage 또는 usage만 입력해주세요.' : usageText(stored.github_usage);
  }
  else if (cmd.toLowerCase() === 'logs') {
    const selected = ({'수집':'collect','긴급':'alerts','발송':'dispatch'})[args] || args.toLowerCase();
    if (m.chat.type !== 'private') text='운영 기록은 봇과의 개인 대화에서 /logs로 확인해주세요.';
    else if (!['','collect','alerts','dispatch'].includes(selected)) text='/logs 또는 /logs collect, /logs alerts, /logs dispatch를 입력해주세요.';
    else return {chat:m.chat.id, logs:selected};
  }
  else if (cmd === 'start' || cmd === 'help') text = HELP;
  else if (cmd === 'subscribe') {
    if (!options && Object.keys(payload.chats).length >= 5) text = '최대 5개 방까지 구독할 수 있습니다. 다른 방에서 /unsubscribe 후 다시 시도하세요.';
    else {
      payload.chats[chat] ||= structuredClone(DEFAULTS);
      options = payload.chats[chat]; changed = true;
      text = '✅ 이 방의 뉴스 구독을 연결했습니다. /status로 확인하세요.';
    }
  } else if (cmd === 'unsubscribe') {
    delete payload.chats[chat]; changed = true;
    text = '이 방의 뉴스 구독을 해제했습니다. /subscribe로 다시 연결할 수 있습니다.';
  } else if (!options) text = '먼저 이 방에서 /subscribe를 보내주세요.';
  else if (cmd === 'status') {
    text = `긴급: ${options.urgent?'켜짐':'꺼짐'} · 아침 동향: ${options.daily?'켜짐':'꺼짐'}\n강도: ${options.mode} · 일일 상한: ${options.limit || '없음'}\n휴식(KST): ${options.quiet}\n관심: ${options.watch.join(', ') || '없음'}\n제외: ${options.exclude.join(', ') || '없음'}\n수집: 24시간 15분 간격 · AI 알림: 06:00~23:30 매시 00/30분 (예약 지연 가능)`;
  } else if (['urgent','daily'].includes(cmd) && ['on','off'].includes(args)) {
    options[cmd] = args === 'on'; changed = true; text = `✅ ${cmd} ${args} 적용했습니다.`;
  } else if (cmd === 'mode' && ['strict','standard'].includes(args)) {
    options.mode=args; changed=true; text=`✅ 알림 강도 ${args} 적용했습니다.`;
  } else if (cmd === 'limit' && /^(?:[0-9]|1[0-9]|20)$/.test(args)) {
    options.limit=Number(args); changed=true; text=`✅ 긴급 알림 하루 ${Number(args) || '제한 없음'}${Number(args)?'건':''} 적용했습니다.`;
  } else if (cmd === 'quiet' && (args === 'off' || /^(?:[01][0-9]|2[0-3])-(?:[01][0-9]|2[0-3])$/.test(args))) {
    if (args !== 'off' && args.slice(0,2) === args.slice(3)) text='시작과 종료 시각을 다르게 입력하세요.';
    else {options.quiet=args; changed=true; text=`✅ 긴급 알림 휴식 시간 ${args} (KST) 적용했습니다.`;}
  } else if (['watch','exclude'].includes(cmd)) {
    const [op, ...parts] = args.split(/\s+/); const word=parts.join(' ').trim();
    if (op === 'list') text = `${cmd}: ${options[cmd].join(', ') || '없음'}`;
    else if (!['add','remove'].includes(op) || !word || word.length>30 || /[\r\n]/.test(word)) text=`/${cmd} add 키워드 또는 /${cmd} remove 키워드 (1~30자)`;
    else if (op === 'add' && options[cmd].length>=10 && !options[cmd].includes(word)) text='키워드는 종류별 최대 10개입니다.';
    else {
      options[cmd] = op==='add' ? [...new Set([...options[cmd],word])] : options[cmd].filter(x=>x!==word);
      changed=true; text=`✅ ${cmd}: ${options[cmd].join(', ') || '없음'}`;
    }
  } else text='명령 형식을 확인해주세요. /help로 사용법을 볼 수 있습니다.';
  if (changed) payload.recent=[...(payload.recent || []),{id:update.update_id,text}].slice(-30);
  return {chat:m.chat.id, text, ...(changed?{payload}: {})};
}

export function isCommandText(text) {
  return typeof text === 'string' && (text.startsWith('/') || /^(usage|logs)$/i.test(text.trim()));
}
