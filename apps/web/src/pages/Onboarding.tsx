import { useState } from 'react'
import { api } from '../api'
import type { Me } from '../App'
import { BrandMark } from '../components/Brand'

/** Първоначален съветник: смяна на началната парола + кратка разходка.
 *  Показва се само докато admin ползва началната парола (или до отказ). */
export default function Onboarding({ me, refreshMe, onClose }: {
  me: Me; refreshMe: () => void; onClose: () => void
}) {
  const [step, setStep] = useState(0)
  const [oldPw, setOldPw] = useState('P@sswordG@te')
  const [newPw, setNewPw] = useState('')
  const [repeat, setRepeat] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function finish() {
    localStorage.setItem('mg_onboarding_done', '1')
    onClose()
  }

  async function changePw(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    if (newPw.length < 8) return setErr('новата парола трябва да е поне 8 знака')
    if (newPw !== repeat) return setErr('паролите не съвпадат')
    setBusy(true)
    try {
      await api('/v1/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
      })
      await refreshMe()
      setStep(2)
    } catch (e2: any) { setErr(e2.message) } finally { setBusy(false) }
  }

  return (
    <div className="modal-back">
      <div className="modal card" style={{ maxWidth: 520 }}>
        {step === 0 && (
          <>
            <h2><BrandMark size={18} /> Добре дошъл в MeshGate</h2>
            <p className="muted small">
              Твоята платформа за месх мрежи: приема съобщения от брокера, разбира
              ги и ги препраща по правила — между канали, към външни брокери, към
              аларми. Три бързи стъпки и си готов.
            </p>
            <div className="small" style={{ display: 'grid', gap: 6, margin: '12px 0' }}>
              <span>1️⃣ Ще сменим началната парола (30 сек)</span>
              <span>2️⃣ Къде какво да гледаш (30 сек)</span>
              <span>3️⃣ Първото ти правило — с Помощника, без MQTT (1 мин)</span>
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button className="ghost-btn" onClick={finish}>Пропусни</button>
              <button onClick={() => setStep(1)}>Започваме →</button>
            </div>
          </>
        )}

        {step === 1 && (
          <form onSubmit={changePw}>
            <h2>🔐 Зашити системата</h2>
            <p className="muted small">
              Сега се влизаш с НАЧАЛНАТА парола. Смени я с твоя — другите ти
              сесии се прекъсват автоматично.
            </p>
            <label>Текуща парола
              <input type="password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} />
            </label>
            <label>Нова парола (≥ 8 знака)
              <input type="password" autoFocus value={newPw} onChange={(e) => setNewPw(e.target.value)} />
            </label>
            <label>Повтори новата
              <input type="password" value={repeat} onChange={(e) => setRepeat(e.target.value)} />
            </label>
            {err && <div className="error">{err}</div>}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 8 }}>
              <button className="ghost-btn" type="button" onClick={() => setStep(2)}>Ще я сменя по-късно</button>
              <button disabled={busy || !newPw || !repeat}>{busy ? '…' : 'Смени паролата'}</button>
            </div>
          </form>
        )}

        {step === 2 && (
          <>
            <h2>🧭 Къде какво да гледаш</h2>
            <div className="small" style={{ display: 'grid', gap: 10, margin: '12px 0' }}>
              <div>📊 <strong>Мониторинг</strong> — графика на трафика, канали, батерии на възлите, активност на правилата (обновява се сама).</div>
              <div>🛰 <strong>Packet Explorer</strong> — всяко съобщение, което минава през системата, на живо.</div>
              <div>🔀 <strong>Routing Rules → + Създай правило → Помощник</strong> — правило без знание на MQTT: избираш „Аларма при ниска батерия“, после канала от живия трафик.</div>
              <div>✅ <strong>План & Тестове</strong> — кое кога е готово + чеклист какво да тестваш сам (вкл. сега: отметни този съветник!).</div>
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={finish}>Готово — започвам</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
