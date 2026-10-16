export interface GuideMeta {
  slug: string;
  title: string;
  description: string;
  h1: string;
  date: string;
  updated: string;
  topic: string;
  faq: { q: string; a: string }[];
  related: string[];
  words: number;
}

interface GuideModule {
  frontmatter: Record<string, unknown>;
  Content: any;
  rawContent: () => string;
}

const modules = import.meta.glob("../content/guides/*.md", { eager: true }) as Record<string, GuideModule>;

export const guides: (GuideMeta & { Content: any })[] = Object.entries(modules)
  .map(([file, m]) => {
    const slug = file.split("/").pop()!.replace(/\.md$/, "");
    const f = m.frontmatter as any;
    for (const k of ["title", "description", "h1", "date", "topic"]) if (!f[k]) throw new Error(`Guide ${slug}: frontmatter "${k}" is missing`);
    return {
      slug, title: f.title, description: f.description, h1: f.h1, date: String(f.date), updated: String(f.updated ?? f.date),
      topic: f.topic, faq: f.faq ?? [], related: f.related ?? [], words: m.rawContent().split(/\s+/).filter(Boolean).length, Content: m.Content,
    };
  })
  .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : a.slug.localeCompare(b.slug)));

export const guideIds = new Set(guides.map((g) => `guide-${g.slug}`));
