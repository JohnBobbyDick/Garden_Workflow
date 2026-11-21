import { createContext, useContext } from 'react'

/** Inside a workspace panel pages drop their outer padding and title (the panel header shows it). */
export const EmbeddedContext = createContext(false)
export const useEmbedded = () => useContext(EmbeddedContext)
