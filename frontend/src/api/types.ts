// Types generated from the backend's API schema: run `npm run gen:api` while the backend is up.
import type { components } from './schema';

type Schemas = components['schemas'];

export type User = Schemas['UserOut'];
export type MeIn = Schemas['MeIn'];
export type Token = Schemas['Token'];
export type AuthOptions = Schemas['AuthOptions'];

export type ProjectSummary = Schemas['ProjectSummary'];
export type Project = Schemas['ProjectOut'];
export type ProjectIn = Schemas['ProjectIn'];
export type ProjectPatch = Schemas['ProjectPatch'];
export type Member = Schemas['MemberOut'];
export type MemberIn = Schemas['MemberIn'];
export type MemberPatch = Schemas['MemberPatch'];
export type Role = Member['role'];

export type Milestone = Schemas['MilestoneOut'];
export type MilestoneIn = Schemas['MilestoneIn'];
export type MilestonePatch = Schemas['MilestonePatch'];

export type Task = Schemas['TaskOut'];
export type TaskIn = Schemas['TaskIn'];
export type TaskPatch = Schemas['TaskPatch'];
export type TaskStatus = Task['status'];
export type TaskEvent = Schemas['EventOut'];

export type MyTask = Schemas['MyTaskOut'];
export type AssistOut = Schemas['AssistOut'];
export type Applied = Schemas['Applied'];

export type ScheduleOut = Schemas['ScheduleOut'];
export type QuestionsOut = Schemas['QuestionsOut'];
export type BriefOut = Schemas['BriefOut'];
export type CountOut = Schemas['CountOut'];
export type Notifications = Schemas['NotificationsOut'];
export type Notification = Schemas['NotificationOut'];
export type Overview = Schemas['OverviewOut'];
export type Calendars = Schemas['CalendarsOut'];
export type Meeting = Schemas['MeetingOut'];
export type MeetingIn = Schemas['MeetingIn'];
export type SuggestOut = Schemas['SuggestOut'];
export type Provider = Schemas['CalendarOut']['provider'];
export type Chats = Schemas['ChatsOut'];
export type Chat = Schemas['ChatOut'];
export type ChatMessage = Schemas['MessageOut'];
