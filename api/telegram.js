import {command, db, validSecret, isCommandText} from './_bot.js';
import {json} from './_lib.js';
import {logsText} from './_logs.js';

export default async function handler(req,res) {
  if (req.method!=='POST') return json(res,405,{ok:false});
  try {
    if (!validSecret(req.headers['x-telegram-bot-api-secret-token'])) return json(res,403,{ok:false});
    if (!isCommandText(req.body?.message?.text)) return json(res,200,{ok:true});
    for(let attempt=0; attempt<3; attempt++) {
      const rows=await db('GET','id=eq.main&select=payload,revision');
      if(!rows.length) return json(res,503,{ok:false});
      const {payload,revision}=rows[0];
      const result=command(req.body,payload);
      if(!result) return json(res,200,{ok:true});
      if(result.logs !== undefined) result.text = await logsText(payload.github_usage, result.logs);
      if(result.payload) {
        const saved=await db('PATCH',`id=eq.main&revision=eq.${revision}`,{
          payload:result.payload,revision:revision+1,updated_at:new Date().toISOString(),
        });
        if(!saved.length) continue;
      }
      // Telegram executes this API method from the webhook response. No bot token
      // is stored on Vercel. Plain chat messages are neither stored nor logged.
      return json(res,200,{method:'sendMessage',chat_id:result.chat,text:result.text,disable_web_page_preview:true});
    }
    return json(res,503,{ok:false});
  } catch {
    return json(res,503,{ok:false});
  }
}
