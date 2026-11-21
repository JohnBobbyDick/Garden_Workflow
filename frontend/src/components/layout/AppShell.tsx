import clsx from 'clsx'
import { useTranslation } from 'react-i18next'
import { useUi } from '../../store/ui'
import { Icon } from '../ui/Icon'
import { useEmbedded } from './embedded'

/* Shared page chrome: theme/language toggles and the page container (padding-less inside workspace panels). */

export function ThemeLangToggles({ stacked = false }: { stacked?: boolean }) {
  const { t } = useTranslation()
  const { theme, toggleTheme, lang, setLang } = useUi()
  return (
    <div className={clsx("flex items-center gap-1", stacked && "flex-col")}>
      <button
        type="button" onClick={toggleTheme} className="rounded-chip p-2 text-muted hover:bg-soft hover:text-fg"
        aria-label={`${t('common.theme')}: ${theme === 'dark' ? t('common.dark') : t('common.light')}`}
        title={`${t('common.theme')}: ${theme === 'dark' ? t('common.dark') : t('common.light')}`}
      >
        <Icon name={theme === 'dark' ? 'moon' : 'sun'} size={17} />
      </button>
      <button
        type="button" onClick={() => setLang(lang === 'ru' ? 'en' : 'ru')}
        className="flex items-center gap-1 rounded-chip px-2 py-2 text-[13px] font-bold text-muted hover:bg-soft hover:text-fg"
        aria-label={`${t('common.language')}: ${lang.toUpperCase()}`}
      >
        <Icon name="lang" size={16} />{lang.toUpperCase()}
      </button>
    </div>
  )
}

export function Page({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
  const embedded = useEmbedded()
  if (embedded) return <div className="w-full px-5 py-5">{children}</div>
  return <div className={clsx('mx-auto w-full px-4 py-6 lg:px-[52px] lg:py-7', wide ? 'max-w-[1600px]' : 'max-w-[1440px]')}>{children}</div>
}
