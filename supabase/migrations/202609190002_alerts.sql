begin;
create table if not exists public.news_alert_state (
  id text primary key check (id = 'urgent'),
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  updated_at timestamptz not null default now()
);
alter table public.news_alert_state enable row level security;
revoke all on public.news_alert_state from anon, authenticated;
grant select, insert, update on public.news_alert_state to service_role;
commit;
