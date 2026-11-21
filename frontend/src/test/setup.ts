/// <reference types="vitest/jsdom" />
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// Node 25 also defines localStorage. Use the current test document's browser storage.
vi.stubGlobal('localStorage', jsdom.window.localStorage)

afterEach(() => cleanup())
