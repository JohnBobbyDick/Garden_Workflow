import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import type { User } from '../api/types'
import { ThemeLangToggles } from '../components/layout/AppShell'
import { Button, Field, Input } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { useAuth } from '../store/auth'
import { useUi } from '../store/ui'

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const { t } = useTranslation()
  const lang = useUi((s) => s.lang)
  const { accessToken, setTokens } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [sentTo, setSentTo] = useState('')
  const [code, setCode] = useState('')
  const verifying = mode === 'register' && !!sentTo

  if (accessToken) return <Navigate to="/" replace />

  const requestCode = async () => {
    await api('/api/auth/registration-code', { method: 'POST', json: { email, locale: lang } })
    setSentTo(email)
    setCode('')
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'register' && !verifying) {
        await requestCode()
        return
      }
      const body = mode === 'login'
        ? await api<{ access_token: string; refresh_token: string; user: User }>('/api/auth/login', { method: 'POST', json: { email, password } })
        : await api<{ access_token: string; refresh_token: string; user: User }>('/api/auth/register', {
          method: 'POST', json: { email: sentTo, password, display_name: name, locale: lang, code } })
      setTokens(body.access_token, body.refresh_token, body.user)
      navigate('/')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('common.unknownError'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-full flex-col">
      <div className="flex justify-end p-3"><ThemeLangToggles /></div>
      <div className="mx-auto grid w-full max-w-5xl flex-1 items-center gap-10 px-4 pb-12 md:grid-cols-2">
        <div className="hidden md:block">
          <div className="mb-6 flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-chip bg-primary text-lg font-bold text-white" aria-hidden="true">✳</span>
            <div>
              <div className="text-2xl font-bold">{t('app.name')}</div>
              <div className="text-muted">{t('app.tagline')}</div>
            </div>
          </div>
          <p className="mb-6 text-lg">{t('auth.welcome')}</p>
          <ul className="space-y-3 text-sm text-muted">
            {([['key', 'secrets'], ['package', 'sca'], ['bug', 'sast'], ['sparkles', 'ai'], ['send', 'notify']] as const).map(([icon, k]) => (
              <li key={k} className="flex items-center gap-3">
                <span className="rounded-field bg-primary/15 p-2 text-primary"><Icon name={icon} size={16} /></span>
                {t(`auth.features.${k}`)}
              </li>
            ))}
          </ul>
        </div>
        <form onSubmit={submit} className="card mx-auto w-full max-w-sm p-6" aria-labelledby="auth-title">
          <h1 id="auth-title" className="mb-5 text-xl font-semibold">{mode === 'login' ? t('auth.login') : t('auth.register')}</h1>
          {mode === 'register' && !verifying && (
            <Field label={t('auth.displayName')} htmlFor="name">
              <Input id="name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
            </Field>
          )}
          {!verifying && <><Field label={t('auth.email')} htmlFor="email" required>
            <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </Field>
          <Field label={t('auth.password')} htmlFor="password" required hint={mode === 'register' ? t('auth.passwordHint') : undefined}>
            <Input id="password" type="password" required minLength={mode === 'register' ? 10 : undefined} value={password}
              onChange={(e) => setPassword(e.target.value)} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
          </Field></>}
          {verifying && <Field label={t('auth.code')} htmlFor="registration-code" required
            hint={t('auth.codeSent', { email: sentTo })}>
            <Input id="registration-code" autoFocus inputMode="numeric" autoComplete="one-time-code"
              required pattern="[0-9]{6}" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} />
          </Field>}
          {error && <p role="alert" className="mb-3 rounded-field bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
          <Button type="submit" variant="primary" className="w-full" loading={busy}>
            {mode === 'login' ? t('auth.submitLogin') : t(verifying ? 'auth.submitRegister' : 'auth.sendCode')}
          </Button>
          {verifying && <div className="mt-3 flex flex-wrap justify-between gap-2">
            <Button type="button" size="sm" disabled={busy} onClick={async () => {
              setBusy(true)
              setError(null)
              try { await requestCode() } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
            }}>{t('auth.resendCode')}</Button>
            <Button type="button" size="sm" disabled={busy} onClick={() => {
              setSentTo(''); setCode(''); setError(null)
            }}>{t('auth.changeEmail')}</Button>
          </div>}
          <p className="mt-4 text-center text-sm text-muted">
            {mode === 'login' ? t('auth.noAccount') : t('auth.haveAccount')}{' '}
            <Link className="font-medium text-primary hover:underline" to={mode === 'login' ? '/register' : '/login'}>
              {mode === 'login' ? t('auth.register') : t('auth.login')}
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
