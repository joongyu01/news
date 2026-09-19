begin;
create table if not exists public.news_bot_settings (
  id text primary key check (id = 'main'),
  payload jsonb not null check (jsonb_typeof(payload) = 'object' and octet_length(payload::text) <= 65536),
  revision bigint not null default 0,
  updated_at timestamptz not null default now()
);
alter table public.news_bot_settings enable row level security;
revoke all on public.news_bot_settings from anon, authenticated;
grant select, insert, update on public.news_bot_settings to service_role;
commit;
