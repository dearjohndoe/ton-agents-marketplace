import type { ArgSchema } from '../../types'

export function InputFields({ schema, fields, setFields, setFileFields, disabled }: {
  schema: Record<string, ArgSchema>
  fields: Record<string, string>
  setFields: React.Dispatch<React.SetStateAction<Record<string, string>>>
  setFileFields: React.Dispatch<React.SetStateAction<Record<string, File>>>
  disabled: boolean
}) {
  if (Object.keys(schema).length === 0) {
    return <p className="state-msg state-msg--sm">No schema available</p>
  }
  return <>
    {Object.entries(schema).map(([name, arg]) => (
      <div key={name} className="field">
        <label>
          <span>{name}{arg.required && <span className="required">*</span>}</span>
          {arg.description && <span className="field-desc">{arg.description}</span>}
        </label>
        {arg.type === 'file' ? (
          <input type="file" disabled={disabled}
            onChange={e => {
              const f = e.target.files?.[0]
              if (f) {
                setFileFields(prev => ({ ...prev, [name]: f }))
                if ('file_name' in schema) {
                  setFields(prev => ({ ...prev, file_name: f.name }))
                }
              }
            }}
          />
        ) : arg.type === 'boolean' ? (
          <select value={fields[name] ?? 'false'} disabled={disabled}
            onChange={e => setFields(f => ({ ...f, [name]: e.target.value }))}>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        ) : arg.type === 'number' ? (
          <input type="number"
            value={fields[name] ?? ''} required={arg.required} disabled={disabled}
            onChange={e => setFields(f => ({ ...f, [name]: e.target.value }))} />
        ) : (
          <textarea rows={3}
            value={fields[name] ?? ''} required={arg.required} disabled={disabled}
            onChange={e => setFields(f => ({ ...f, [name]: e.target.value }))} />
        )}
      </div>
    ))}
  </>
}
