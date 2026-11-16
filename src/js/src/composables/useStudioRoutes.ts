import { ref, computed, watch, nextTick } from 'vue'
import type { Ref } from 'vue'
import type { RouteLocationNormalizedLoaded, Router } from 'vue-router'
import type { Space, ThreadKind } from './studioTypes'
import type { Studio } from './useStudio'

// Where the Studio is: its centre pane (a thread, the settings, media…) is a real route so the back button works.
// Holds the route-derived view state, the navigation helpers the panes call, and the sync from route to state.

/** The pane in the middle: a thread, or one of the other pages. */
export type CenterPane =
  | 'thread'
  | 'space'
  | 'media'
  | 'settings'
  | 'tools'
  | 'usage'
  | 'characters'
  | 'presets'
  | 'instructions'
  | 'requests'
  | 'favourites'

/** The sidebar's list filter (Favourites is its own route). */
export type NavFilter = 'all' | 'chat' | 'gallery'

// Settings "Tools" links → in-Studio panes.
const STUDIO_PANE_PATH: Readonly<Record<string, string>> = {
  usage: '/usage',
  characters: '/characters',
  instructions: '/instructions',
  'request-log': '/requests',
  presets: '/presets',
}

// Which center pane each route name shows (threads handled separately below).
const PANE_FOR_ROUTE: Readonly<Record<string, CenterPane>> = {
  'studio-settings': 'settings',
  'studio-tools': 'tools',
  'studio-media': 'media',
  'studio-usage': 'usage',
  'studio-characters': 'characters',
  'studio-presets': 'presets',
  'studio-instructions': 'instructions',
  'studio-requests': 'requests',
  'studio-favourites': 'favourites',
  'studio-space': 'space',
}

/** A route parameter as one string, or null when it is missing or repeated. */
const paramOf = (value: string | string[] | undefined): string | null => (typeof value === 'string' ? value : null)

interface RouteHooks {
  router: Router
  route: RouteLocationNormalizedLoaded
  studio: Pick<
    Studio,
    | 'threads'
    | 'spaces'
    | 'active'
    | 'activeKind'
    | 'newThread'
    | 'openThread'
    | 'loadStatus'
    | 'loadFavourites'
    | 'setThreadKind'
    | 'removeSpace'
  >
  threadView: Ref<'chat' | 'gallery'>
}

export function useStudioRoutes({ router, route, studio, threadView }: RouteHooks) {
  const {
    threads,
    spaces,
    active,
    activeKind,
    newThread,
    openThread,
    loadStatus,
    loadFavourites,
    setThreadKind,
    removeSpace,
  } = studio
  const navFilter = ref<NavFilter>('all') // list filter (Favourites is its own route)
  const centerView = ref<CenterPane>('thread') // derived from the route
  // The sidebar shows Favourites as active when its route is open.
  const sidebarFilter = computed(() => (centerView.value === 'favourites' ? 'favourites' : navFilter.value))

  function onFilter(filter: NavFilter | 'favourites'): void {
    if (filter === 'favourites') {
      void router.push('/favourites')
      return
    }
    navFilter.value = filter
    if (centerView.value === 'favourites') goThread()
  }

  const activeSpace = ref<Space | null>(null)
  const spaceThreads = computed(() => threads.value.filter(t => t.space_id === activeSpace.value?.id))

  function ensureSpace(spaceId: string | null): void {
    const found = spaces.value.find(s => s.id === Number(spaceId))
    if (found) activeSpace.value = found
  }
  // The space may not be loaded yet on a cold deep-link; bind it once lists load.
  watch(spaces, () => {
    if (route.name === 'studio-space') ensureSpace(paramOf(route.params['spaceId']))
  })

  function openSpace(space: Space): void {
    void router.push(`/space/${String(space.id)}`)
  }
  async function deleteSpaceView(space: Space): Promise<void> {
    await removeSpace(space)
    if (activeSpace.value?.id === space.id) goThread()
  }

  let pendingKind: ThreadKind = 'chat' // the kind a brand-new thread (/) opens on
  function goThread(): void {
    void router.push(active.value ? `/${active.value}` : '/')
  }
  function goSettings(): void {
    void router.push('/settings')
  }
  function goTools(): void {
    void router.push('/tools')
  }
  function goMedia(): void {
    void router.push('/media')
  }
  function goInstructions(): void {
    void router.push('/instructions')
  }
  function openThreadView(id: string): void {
    void router.push(`/${id}`)
  }

  const composerRef = ref<{ focusPrompt: () => void } | null>(null)
  async function newThreadView(kind: ThreadKind = 'chat'): Promise<void> {
    pendingKind = kind
    // ?new=gallery so the link opens as a gallery in a new tab too
    const to = kind === 'gallery' ? '/?new=gallery' : '/'
    if (route.name === 'studio') {
      newThread(kind) // already on the home route: just reset
    } else {
      await router.push(to)
    }
    await nextTick()
    composerRef.value?.focusPrompt()
  }

  // One toggle does both jobs: it switches the view *and* makes that the view the
  // thread opens on next time (there is no separate "default view" switch).
  function setThreadView(view: ThreadKind): void {
    if (activeKind.value !== view) void setThreadKind(view)
    if (active.value) void router.push(`/${active.value}/${view}`)
    else threadView.value = view // unsaved new thread has no id to route
  }

  function onSettingsNavigate(dest: string): void {
    const path = STUDIO_PANE_PATH[dest]
    void router.push(path ?? { name: dest })
  }

  function openPane(pane: CenterPane): void {
    centerView.value = pane
    if (pane === 'usage')
      void loadStatus() // refresh balances when opening usage
    else if (pane === 'favourites') void loadFavourites()
    else if (pane === 'space') ensureSpace(paramOf(route.params['spaceId']))
  }

  // studio-thread (/:id[/:view]) or studio (/ = new thread)
  async function openThreadRoute(): Promise<void> {
    centerView.value = 'thread'
    const id = paramOf(route.params['id'])
    if (!id) {
      // ?new=gallery lets "New gallery" work as a link (opened in a new tab,
      // bookmarked), not just as a click that set pendingKind on the way here
      newThread(route.query['new'] === 'gallery' ? 'gallery' : pendingKind)
      pendingKind = 'chat'
      return
    }
    // A thread that fails to load (stale URL) falls back to home.
    if (id !== active.value && !(await openThread(id))) {
      await router.replace('/')
      return
    }
    const view = route.params['view']
    if (view === 'chat' || view === 'gallery') threadView.value = view
  }

  // Drive the center pane + active thread from the current route.
  async function syncFromRoute(): Promise<void> {
    const pane = typeof route.name === 'string' ? PANE_FOR_ROUTE[route.name] : undefined
    if (pane) openPane(pane)
    else await openThreadRoute()
  }
  watch(
    () => route.fullPath,
    () => void syncFromRoute(),
  )

  // When a thread appears/changes outside navigation (first send on a new thread,
  // or a fork), reflect its id in the URL so the address bar and back button stay
  // correct. replace (not push) so back doesn't land on the empty /studio.
  watch(active, id => {
    if (id && centerView.value === 'thread' && route.params['id'] !== id) void router.replace(`/${id}`)
  })

  return {
    centerView,
    sidebarFilter,
    onFilter,
    activeSpace,
    spaceThreads,
    composerRef,
    openSpace,
    deleteSpaceView,
    goThread,
    goSettings,
    goTools,
    goMedia,
    goInstructions,
    openThreadView,
    newThreadView,
    setThreadView,
    onSettingsNavigate,
    syncFromRoute,
  }
}
