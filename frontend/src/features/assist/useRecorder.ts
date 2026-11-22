import { useEffect, useRef, useState } from 'react';

const MAX_SECONDS = 60;

/**
 * Records from the microphone until stopped (or a minute passes), then hands over the audio.
 * Needs HTTPS or localhost; browsers refuse the mic anywhere else.
 */
export function useRecorder(onAudio: (audio: Blob, filename: string) => void) {
  const [recording, setRecording] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const latest = useRef(onAudio);
  useEffect(() => {
    latest.current = onAudio;
  }, [onAudio]);

  const supported = typeof window !== 'undefined' && 'MediaRecorder' in window && !!navigator.mediaDevices?.getUserMedia;

  const stop = () => {
    window.clearTimeout(timer.current);
    if (recorder.current?.state === 'recording') recorder.current.stop();
  };

  const start = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const rec = new MediaRecorder(stream);
    const chunks: Blob[] = [];
    rec.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    rec.onstop = () => {
      stream.getTracks().forEach((track) => track.stop()); // turns the browser's mic indicator off
      setRecording(false);
      const type = rec.mimeType || 'audio/webm';
      const extension = type.includes('mp4') ? 'mp4' : type.includes('ogg') ? 'ogg' : 'webm';
      if (chunks.length) latest.current(new Blob(chunks, { type }), `voice.${extension}`);
    };
    rec.start();
    recorder.current = rec;
    setRecording(true);
    timer.current = window.setTimeout(stop, MAX_SECONDS * 1000);
  };

  useEffect(() => {
    // Leaving the page mid-recording releases the mic.
    const rec = recorder;
    return () => {
      if (rec.current?.state === 'recording') rec.current.stop();
    };
  }, []);
  return { supported, recording, start, stop };
}
