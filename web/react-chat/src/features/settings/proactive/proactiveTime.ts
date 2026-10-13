export const minuteText = (value:number) =>
  `${String(Math.floor(value / 60)).padStart(2,'0')}:${String(value % 60).padStart(2,'0')}`;

export const parseMinute = (value:string) => {
  const [hour, minute] = value.split(':').map(Number);
  return hour * 60 + minute;
};
