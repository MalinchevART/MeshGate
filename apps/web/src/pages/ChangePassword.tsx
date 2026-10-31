import { useState } from 'react'
import { api } from '../api'

export default function ChangePassword({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [oldPw, setOldPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [okMsg, setOkMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (newPw.length < 8) return setError('новата парола трябва да е поне 8 знака')
    if (newPw !== repeat) return setError('паролите не съвпадат')
    setBusy(true)
    try {
      await api('/v1/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
      })
      setOkMsg('Паролата е сменена. Другите ти сесии са прекъснати.')
      setTimeout(() => { onDone(); onClose() }, 1200)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-back" onClick={okMsg ? onClose : undefined}>
      <form className="modal card" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>Смяна на парола</h2>
        <input type="password" autoFocus placeholder="текуща парола" value={oldPw}
               onChange={(e) => setOldPw(e.target.value)} />
        <input type="password" placeholder="нова парола (мин. 8 знака)" value={newPw}
               onChange={(e) => setNewPw(e.target.value)} />
        <input type="password" placeholder="нова парола повторно" value={repeat}
               onChange={(e) => setRepeat(e.target.value)} />
        {error && <div className="error">{error}</div>}
        {okMsg && <div className="ok-box">{okMsg}</div>}
        <div className="form-row">
          <button type="button" className="ghost-btn" onClick={onClose} disabled={!!okMsg}>Затвори</button>
          <button disabled={busy || !oldPw || !newPw}>{busy ? '…' : 'Смени'}</button>
        </div>
      </form>
    </div>
  )
}
