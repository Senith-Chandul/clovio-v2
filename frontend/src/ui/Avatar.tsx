interface AvatarProps {
  name: string;
  src?: string;
  size?: 'sm' | 'md' | 'lg';
  online?: boolean;
  className?: string;
}

const SIZE_CLASS = { sm: 'clv-avatar-sm', md: '', lg: 'clv-avatar-lg' };
// One tint per person, kept everywhere: picked from the name so it never changes between pages.
const TINTS = ['', 'clv-avatar-2', 'clv-avatar-3', 'clv-avatar-4'];

const initialsOf = (name: string): string => {
  const words = name.trim().split(/\s+/);
  return (words.length >= 2 ? `${words[0][0]}${words[1][0]}` : name.slice(0, 2)).toUpperCase();
};

const tintOf = (name: string): string => {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return TINTS[hash % TINTS.length];
};

export default function Avatar({ name, src, size = 'md', online = false, className = '' }: AvatarProps) {
  return (
    <span className={`clv-avatar ${SIZE_CLASS[size]} ${src ? '' : tintOf(name)} ${className}`} title={name}>
      {src ? <img src={src} alt={name} className="h-full w-full rounded-full object-cover" /> : initialsOf(name)}
      {online && <span className="clv-presence" />}
    </span>
  );
}
