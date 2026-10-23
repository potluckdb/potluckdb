// The docs site, docs.potluckdb.com. Built from this folder on every change;
// published from each release (PRD E5).
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightLlmsTxt from 'starlight-llms-txt';

export default defineConfig({
  site: 'https://docs.potluckdb.com',
  integrations: [
    starlight({
      title: 'PotluckDB',
      description: 'Local-first SQLite and DuckDB, synced through a storage bucket you own.',
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/potluckdb/potluckdb' }],
      editLink: { baseUrl: 'https://github.com/potluckdb/potluckdb/edit/main/docs/' },
      plugins: [starlightLlmsTxt()],
      sidebar: [
        { label: 'Start here', items: [{ autogenerate: { directory: 'start' } }] },
        { label: 'Guides', items: [{ autogenerate: { directory: 'guides' } }] },
        { label: 'Reference', items: [{ autogenerate: { directory: 'reference' } }] },
      ],
    }),
  ],
});
