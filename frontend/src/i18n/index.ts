import i18n from 'i18next'
import { initReactI18next, useTranslation } from 'react-i18next'
import type { I18nText, Lang } from '../api/types'
import en from './en'
import ru from './ru'

const stored = (typeof localStorage !== 'undefined' && localStorage.getItem('aisw.lang')) as Lang | null

void i18n.use(initReactI18next).init({
  resources: { ru: { translation: ru }, en: { translation: en } },
  lng: stored ?? 'ru',
  fallbackLng: 'ru',
  interpolation: { escapeValue: false },
  returnNull: false,
})

export default i18n

export function useLang(): Lang {
  const { i18n: inst } = useTranslation()
  return (inst.language?.startsWith('en') ? 'en' : 'ru') as Lang
}

export function pick(text: I18nText | undefined, lang: Lang): string {
  if (!text) return ''
  return text[lang] || text.ru || text.en || ''
}
