import { useTranslation } from 'react-i18next';

const LANGS = [
  { code: 'zh', label: '中' },
  { code: 'en', label: 'EN' },
  { code: 'fr', label: 'FR' },
];

export default function LanguageSwitcher() {
  const { i18n } = useTranslation();

  const current = i18n.language?.split('-')[0] || 'zh';
  const currentIdx = LANGS.findIndex(l => l.code === current);
  const next = LANGS[(currentIdx + 1) % LANGS.length];

  return (
    <button
      onClick={() => i18n.changeLanguage(next.code)}
      className="w-10 h-10 rounded-full bg-white/70 backdrop-blur-md border border-white shadow-sm flex items-center justify-center text-xs font-bold text-indigo-600 hover:bg-white hover:scale-110 active:scale-95 transition-all cursor-pointer select-none"
      title={`${LANGS.find(l => l.code === current)?.label} → ${next.label}`}
    >
      {LANGS.find(l => l.code === current)?.label || current.toUpperCase()}
    </button>
  );
}
