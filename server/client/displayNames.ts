export function readableId(id: string): string {
  if (!id) return ''
  return id
    .replace(/[_-]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ')
    .split(' ')
    .map((word) => (word ? word[0].toUpperCase() + word.slice(1) : word))
    .join(' ')
}

export function roomDisplayName(roomKey: string | null, roomName?: string): string {
  if (roomName && roomName.trim()) return roomName.trim()
  return readableId(roomKey || '')
}

export function disguiseDisplayName(disguiseId: string | null, stateName?: string): string {
  if (stateName && stateName.trim()) return stateName.trim()
  return readableId(disguiseId || '')
}

export function missionDisplayTitle(
  missionId: string,
  activeMissions: Array<{ mission_id: string; title?: string }>
): string {
  const match = activeMissions.find((mission) => mission.mission_id === missionId)
  if (match && match.title && match.title.trim()) return match.title.trim()
  return readableId(missionId)
}

export function npcDisplayName(npcId: string, knownName?: string): string {
  if (knownName && knownName.trim()) return knownName.trim()
  return readableId(npcId)
}
