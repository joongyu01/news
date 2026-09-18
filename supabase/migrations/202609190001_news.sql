begin;
create table public.news_drafts (
  date date primary key,
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  updated_at timestamptz not null default now()
);
create table public.news_exclusions (
  date date primary key references public.news_drafts(date),
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  updated_at timestamptz not null default now()
);
alter table public.news_drafts enable row level security;
alter table public.news_exclusions enable row level security;
revoke all on public.news_drafts, public.news_exclusions from anon, authenticated;
grant select, insert, update on public.news_drafts, public.news_exclusions to service_role;
commit;
