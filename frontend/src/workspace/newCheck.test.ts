import { describe, expect, it } from 'vitest'
import { validateRepoInput } from './newCheck'

describe('validateRepoInput: what a person pastes into «Что проверяем?»', () => {
  it('accepts a full https link and trims spaces', () => {
    expect(validateRepoInput('  https://github.com/a/b.git ')).toEqual({ ok: true, url: 'https://github.com/a/b.git' })
    expect(validateRepoInput('https://gitlab.com/g/p/-/tree/main')).toEqual({ ok: true, url: 'https://gitlab.com/g/p/-/tree/main' })
  })
  it('explains what is wrong', () => {
    expect(validateRepoInput('')).toEqual({ ok: false, reason: 'empty' })
    expect(validateRepoInput('   ')).toEqual({ ok: false, reason: 'empty' })
    expect(validateRepoInput('http://github.com/x/y')).toEqual({ ok: false, reason: 'not_https' })
    expect(validateRepoInput('github.com/x/y')).toEqual({ ok: false, reason: 'not_url' })
    expect(validateRepoInput('https://')).toEqual({ ok: false, reason: 'not_url' })
    expect(validateRepoInput('https://github.com')).toEqual({ ok: false, reason: 'not_url' })
  })
})
