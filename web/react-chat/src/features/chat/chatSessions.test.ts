import {describe, expect, test} from 'vitest';
import {organizeChats, readPinnedChats, togglePinnedChat, writePinnedChats} from './chatSessions';

const chats = [
  {chat_id:'recent', title:'今天的聊天', turn_count:2},
  {chat_id:'cat', title:'豆包的近况', turn_count:5},
  {chat_id:'work', title:'毕业设计', turn_count:8},
];

describe('聊天会话整理', () => {
  test('置顶排在最近会话前，未置顶会话保留服务端顺序', () => {
    expect(organizeChats(chats, ['work'], '').map(item => item.chat_id)).toEqual(['work','recent','cat']);
  });

  test('搜索标题不区分英文大小写且不搜索聊天正文', () => {
    expect(organizeChats([...chats,{chat_id:'api',title:'API Notes',turn_count:1}], [], 'api'))
      .toEqual([{chat_id:'api',title:'API Notes',turn_count:1}]);
  });

  test('本地置顶只保存去重后的安全会话 ID', () => {
    let raw = '';
    const storage = {getItem:()=>raw,setItem:(_key:string,value:string)=>{raw=value;}};
    expect(writePinnedChats(storage, 'pins', ['cat','cat','work'])).toBe(true);
    expect(readPinnedChats(storage, 'pins')).toEqual(['cat','work']);
    expect(togglePinnedChat(['cat'], 'work')).toEqual(['work','cat']);
    expect(togglePinnedChat(['cat','work'], 'cat')).toEqual(['work']);
  });

  test('损坏或被禁用的本地存储不阻止聊天', () => {
    expect(readPinnedChats({getItem:()=>'{'}, 'pins')).toEqual([]);
    expect(writePinnedChats({setItem:()=>{throw new Error('blocked');}}, 'pins', ['cat'])).toBe(false);
  });
});
