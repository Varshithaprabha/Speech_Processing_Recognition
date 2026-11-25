import { useState } from 'react'

/**
 * Emergency SOS mode: full-screen flashing page with the emergency message in big letters (to show to
 * anyone nearby), large preset phrases, and optional location shown on screen (it is not sent anywhere).
 */
export default function SosOverlay({ alert, onClose, onQuick, onSay, flash }) {
  const [loc, setLoc] = useState(null)
  const [locErr, setLocErr] = useState('')

  const shareLocation = () => {
    if (!navigator.geolocation) return setLocErr('Location is not available on this device.')
    setLocErr('Finding location…')
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setLocErr('')
        setLoc({ lat: p.coords.latitude.toFixed(5), lon: p.coords.longitude.toFixed(5), acc: Math.round(p.coords.accuracy) })
        onSay('My location is shown on my screen.', 'urgent')
      },
      (e) => setLocErr(e.code === 1 ? 'Location permission denied.' : 'Could not get location.'),
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }

  const presets = [
    ['🩺 I need a doctor', () => onSay('I need a doctor, please.', 'urgent')],
    ['👪 Call my family', () => onQuick('family')],
    ['🤕 I am in pain', () => onQuick('pain')],
    ['🚑 Call an ambulance', () => onSay('Please call an ambulance.', 'urgent')],
  ]

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-label="Emergency SOS"
      className={`fixed inset-0 z-50 flex flex-col overflow-y-auto p-6 text-white ${flash ? 'sos-bg' : 'bg-red-700'}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="text-2xl font-black tracking-widest">🆘 EMERGENCY</div>
        <button className="rounded-xl bg-white px-5 py-3 text-lg font-bold text-red-700" onClick={onClose}>
          ✕ Close
        </button>
      </div>
      <p className="my-8 text-4xl leading-tight font-black sm:text-6xl">
        {alert?.sentence || 'Emergency! I am Deaf and I need help right now. Please call a doctor.'}
      </p>
      {alert?.sentence_en && alert.sentence_en !== alert.sentence && (
        <p className="-mt-4 mb-8 text-2xl font-semibold opacity-90">{alert.sentence_en}</p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {presets.map(([label, fn]) => (
          <button
            key={label}
            onClick={fn}
            className="rounded-2xl border-4 border-white bg-red-900/50 px-5 py-6 text-left text-2xl font-bold hover:bg-red-900"
          >
            {label}
          </button>
        ))}
        <button
          onClick={shareLocation}
          className="rounded-2xl border-4 border-white bg-white px-5 py-6 text-left text-2xl font-bold text-red-700 sm:col-span-2"
        >
          📍 Show my location
        </button>
      </div>
      {(loc || locErr) && (
        <div className="mt-4 rounded-2xl bg-white p-5 text-red-800">
          {loc ? (
            <>
              <div className="text-3xl font-black">
                {loc.lat}, {loc.lon}
              </div>
              <div className="text-base">accuracy ±{loc.acc} m</div>
              <a
                className="mt-2 inline-block text-lg font-bold underline"
                href={`https://www.google.com/maps?q=${loc.lat},${loc.lon}`}
                target="_blank"
                rel="noreferrer"
              >
                Open in Maps
              </a>
            </>
          ) : (
            <div className="text-lg font-semibold">{locErr}</div>
          )}
        </div>
      )}
    </div>
  )
}
