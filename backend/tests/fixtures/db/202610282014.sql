BEGIN TRANSACTION;
CREATE TABLE alembic_version (
	version_num VARCHAR(32) NOT NULL, 
	CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
INSERT INTO "alembic_version" VALUES('202610282014');
CREATE TABLE app_meta (
	id INTEGER NOT NULL, 
	auth_epoch INTEGER NOT NULL, 
	password_hash VARCHAR(200), 
	password_fp VARCHAR(64), 
	secret_key_check VARCHAR(64), 
	last_boot_version VARCHAR(32), instance_id VARCHAR(36), 
	CONSTRAINT pk_app_meta PRIMARY KEY (id), 
	CONSTRAINT ck_app_meta_single_row CHECK (id = 1)
);
INSERT INTO "app_meta" VALUES(1,1,'scrypt$sample$sample',NULL,NULL,'0.1.0','00000000-0000-7000-8000-0000000000e1');
CREATE TABLE calendars (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	color VARCHAR(8) NOT NULL, 
	kind VARCHAR(8) NOT NULL, 
	owner_member_id VARCHAR(36), 
	read_only BOOLEAN NOT NULL, 
	visible_on_display BOOLEAN NOT NULL, 
	version INTEGER NOT NULL, 
	remote_ref VARCHAR(500), 
	sort INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	deleted_at DATETIME, 
	CONSTRAINT pk_calendars PRIMARY KEY (id), 
	CONSTRAINT fk_calendars_owner_member_id_members FOREIGN KEY(owner_member_id) REFERENCES members (id)
);
INSERT INTO "calendars" VALUES('01a1845c-5dee-71d3-b2b8-2454b532ceec','Home','sky','local',NULL,0,1,1,NULL,0,'2026-10-28 21:13:28.302997','2026-10-28 21:13:28.302997',NULL);
INSERT INTO "calendars" VALUES('00000000-0000-7000-8000-000000000401','Kids'' activities','iris','local','00000000-0000-7000-8000-000000000002',0,1,3,NULL,1,'2026-10-08 12:00:00','2026-10-08 12:00:00',NULL);
INSERT INTO "calendars" VALUES('00000000-0000-7000-8000-000000000402','School','olive','sync','00000000-0000-7000-8000-000000000002',1,1,1,'a calendar address',1000,'2026-10-08 18:00:00','2026-10-08 18:00:00',NULL);
CREATE TABLE chore_completions (
	id VARCHAR(36) NOT NULL, 
	chore_id VARCHAR(36) NOT NULL, 
	due_date VARCHAR(10) NOT NULL, 
	member_id VARCHAR(36) NOT NULL, 
	completed_at DATETIME NOT NULL, 
	completed_by_device_id VARCHAR(36), 
	points_awarded INTEGER NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	approved_by_member_id VARCHAR(36), 
	approved_at DATETIME, 
	CONSTRAINT pk_chore_completions PRIMARY KEY (id), 
	CONSTRAINT fk_chore_completions_approved_by_member_id_members FOREIGN KEY(approved_by_member_id) REFERENCES members (id), 
	CONSTRAINT fk_chore_completions_chore_id_chores FOREIGN KEY(chore_id) REFERENCES chores (id), 
	CONSTRAINT fk_chore_completions_member_id_members FOREIGN KEY(member_id) REFERENCES members (id), 
	CONSTRAINT uq_chore_completions_chore_id UNIQUE (chore_id, due_date, member_id)
);
INSERT INTO "chore_completions" VALUES('00000000-0000-7000-8000-000000000a31','00000000-0000-7000-8000-000000000a01','2026-10-08','00000000-0000-7000-8000-000000000002','2026-10-08 23:10:00','00000000-0000-7000-8000-0000000000d2',1,'done',NULL,NULL);
INSERT INTO "chore_completions" VALUES('00000000-0000-7000-8000-000000000a32','00000000-0000-7000-8000-000000000a02','2026-10-07','00000000-0000-7000-8000-000000000002','2026-10-07 21:00:00','00000000-0000-7000-8000-0000000000d2',2,'pending',NULL,NULL);
CREATE TABLE chores (
	id VARCHAR(36) NOT NULL, 
	title VARCHAR(80) NOT NULL, 
	description VARCHAR(500), 
	icon VARCHAR(32), 
	points INTEGER NOT NULL, 
	rrule VARCHAR(500), 
	start_date VARCHAR(10) NOT NULL, 
	due_time VARCHAR(5), 
	assignee_mode VARCHAR(8) NOT NULL, 
	assignee_member_ids_json TEXT NOT NULL, 
	rotation_index INTEGER NOT NULL, 
	requires_approval BOOLEAN, 
	skipped_dates_json TEXT NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_by_member_id VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	deleted_at DATETIME, 
	CONSTRAINT pk_chores PRIMARY KEY (id), 
	CONSTRAINT fk_chores_created_by_member_id_members FOREIGN KEY(created_by_member_id) REFERENCES members (id)
);
INSERT INTO "chores" VALUES('00000000-0000-7000-8000-000000000a01','Empty the dishwasher',NULL,'plate',1,'FREQ=DAILY','2026-10-01','19:00','rotate','["00000000-0000-7000-8000-000000000001", "00000000-0000-7000-8000-000000000002"]',0,NULL,'["2026-10-05"]',1,'00000000-0000-7000-8000-000000000001','2026-10-01 12:00:00','2026-10-05 12:00:00',NULL);
INSERT INTO "chores" VALUES('00000000-0000-7000-8000-000000000a02','Feed the fish','A pinch, not the whole jar.',NULL,2,'FREQ=WEEKLY;BYDAY=MO,WE,FR','2026-10-01',NULL,'fixed','["00000000-0000-7000-8000-000000000002"]',0,1,'[]',1,'00000000-0000-7000-8000-000000000001','2026-10-01 12:00:00','2026-10-01 12:00:00',NULL);
CREATE TABLE countdowns (
	id VARCHAR(36) NOT NULL, 
	title VARCHAR(80) NOT NULL, 
	emoji VARCHAR(16), 
	color VARCHAR(8), 
	date VARCHAR(10) NOT NULL, 
	time VARCHAR(5), 
	repeat_yearly BOOLEAN NOT NULL, 
	member_id VARCHAR(36), 
	show_on_display BOOLEAN NOT NULL, 
	created_by_member_id VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	deleted_at DATETIME, 
	CONSTRAINT pk_countdowns PRIMARY KEY (id), 
	CONSTRAINT fk_countdowns_created_by_member_id_members FOREIGN KEY(created_by_member_id) REFERENCES members (id), 
	CONSTRAINT fk_countdowns_member_id_members FOREIGN KEY(member_id) REFERENCES members (id)
);
INSERT INTO "countdowns" VALUES('00000000-0000-7000-8000-000000000b11','Beach day','🏖️','sky','2027-07-04','09:00',1,'00000000-0000-7000-8000-000000000002',1,'00000000-0000-7000-8000-000000000001','2026-10-08 21:20:00','2026-10-08 21:20:00',NULL);
INSERT INTO "countdowns" VALUES('00000000-0000-7000-8000-000000000b12','Surprise party','🎉',NULL,'2026-11-20',NULL,0,NULL,0,'00000000-0000-7000-8000-000000000001','2026-10-08 21:21:00','2026-10-08 21:21:00',NULL);
CREATE TABLE devices (
	id VARCHAR(36) NOT NULL, 
	label VARCHAR(80) NOT NULL, 
	kind VARCHAR(8) NOT NULL, 
	member_id VARCHAR(36), 
	is_kid_device BOOLEAN NOT NULL, 
	paired_via VARCHAR(12) NOT NULL, 
	created_at DATETIME NOT NULL, 
	last_seen_at DATETIME NOT NULL, 
	revoked_at DATETIME, 
	CONSTRAINT pk_devices PRIMARY KEY (id), 
	CONSTRAINT fk_devices_member_id_members FOREIGN KEY(member_id) REFERENCES members (id) ON DELETE SET NULL
);
INSERT INTO "devices" VALUES('00000000-0000-7000-8000-0000000000d1','iPhone, Safari','phone','00000000-0000-7000-8000-000000000001',0,'password','2026-10-07 12:00:00','2026-10-07 12:30:00',NULL);
INSERT INTO "devices" VALUES('00000000-0000-7000-8000-0000000000d2','Kitchen screen','kiosk',NULL,0,'kiosk_code','2026-10-07 12:10:00','2026-10-07 12:40:00',NULL);
CREATE TABLE event_members (
	event_id VARCHAR(36) NOT NULL, 
	member_id VARCHAR(36) NOT NULL, 
	CONSTRAINT pk_event_members PRIMARY KEY (event_id, member_id), 
	CONSTRAINT fk_event_members_event_id_events FOREIGN KEY(event_id) REFERENCES events (id) ON DELETE CASCADE, 
	CONSTRAINT fk_event_members_member_id_members FOREIGN KEY(member_id) REFERENCES members (id)
);
INSERT INTO "event_members" VALUES('00000000-0000-7000-8000-000000000501','00000000-0000-7000-8000-000000000002');
INSERT INTO "event_members" VALUES('00000000-0000-7000-8000-000000000502','00000000-0000-7000-8000-000000000002');
INSERT INTO "event_members" VALUES('00000000-0000-7000-8000-000000000504','00000000-0000-7000-8000-000000000001');
CREATE TABLE event_reminders (
	event_id VARCHAR(36) NOT NULL, 
	minutes_before INTEGER NOT NULL, 
	CONSTRAINT pk_event_reminders PRIMARY KEY (event_id, minutes_before), 
	CONSTRAINT fk_event_reminders_event_id_events FOREIGN KEY(event_id) REFERENCES events (id) ON DELETE CASCADE
);
INSERT INTO "event_reminders" VALUES('00000000-0000-7000-8000-000000000501',30);
CREATE TABLE event_revisions (
	id VARCHAR(36) NOT NULL, 
	series_id VARCHAR(36) NOT NULL, 
	action VARCHAR(10) NOT NULL, 
	before_json TEXT NOT NULL, 
	created_ids_json TEXT NOT NULL, 
	device_id VARCHAR(36), 
	member_id VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	undone_at DATETIME, 
	CONSTRAINT pk_event_revisions PRIMARY KEY (id)
);
INSERT INTO "event_revisions" VALUES('00000000-0000-7000-8000-000000000601','00000000-0000-7000-8000-000000000504','delete','[]','[]','00000000-0000-7000-8000-0000000000d1','00000000-0000-7000-8000-000000000001','2026-10-08 12:04:00',NULL);
CREATE TABLE "events" (
	id VARCHAR(36) NOT NULL, 
	calendar_id VARCHAR(36) NOT NULL, 
	parent_event_id VARCHAR(36), 
	recurrence_id VARCHAR(19), 
	title VARCHAR(200) NOT NULL, 
	description TEXT NOT NULL, 
	location VARCHAR(300) NOT NULL, 
	all_day BOOLEAN NOT NULL, 
	start_utc DATETIME, 
	end_utc DATETIME, 
	tzid VARCHAR(64), 
	start_date VARCHAR(10), 
	end_date VARCHAR(10), 
	floating BOOLEAN NOT NULL, 
	rrule VARCHAR(500), 
	rdates_json TEXT NOT NULL, 
	exdates_json TEXT NOT NULL, 
	window_start_utc DATETIME NOT NULL, 
	window_end_utc DATETIME NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	color VARCHAR(8), 
	source VARCHAR(8) NOT NULL, 
	remote_uid VARCHAR(500), 
	remote_id VARCHAR(500), 
	etag VARCHAR(200), 
	remote_updated_at DATETIME, 
	remote_sequence INTEGER, 
	pending_push BOOLEAN NOT NULL, 
	pending_delete BOOLEAN NOT NULL, 
	raw_ical TEXT, 
	version INTEGER NOT NULL, 
	created_by_member_id VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	deleted_at DATETIME, 
	people_from_title BOOLEAN DEFAULT 0 NOT NULL, 
	reminders_off BOOLEAN DEFAULT 0 NOT NULL, 
	CONSTRAINT pk_events PRIMARY KEY (id), 
	CONSTRAINT fk_events_parent_event_id_events FOREIGN KEY(parent_event_id) REFERENCES events (id), 
	CONSTRAINT ck_events_override_has_parent CHECK (recurrence_id IS NULL OR parent_event_id IS NOT NULL), 
	CONSTRAINT fk_events_created_by_member_id_members FOREIGN KEY(created_by_member_id) REFERENCES members (id), 
	CONSTRAINT uq_events_calendar_id UNIQUE (calendar_id, remote_uid, recurrence_id), 
	CONSTRAINT fk_events_calendar_id_calendars FOREIGN KEY(calendar_id) REFERENCES calendars (id), 
	CONSTRAINT ck_events_one_timing CHECK ((all_day = 0 AND start_utc IS NOT NULL AND end_utc IS NOT NULL AND tzid IS NOT NULL AND start_date IS NULL AND end_date IS NULL) OR (all_day = 1 AND start_date IS NOT NULL AND end_date IS NOT NULL AND start_utc IS NULL AND end_utc IS NULL))
);
INSERT INTO "events" VALUES('00000000-0000-7000-8000-000000000501','00000000-0000-7000-8000-000000000401',NULL,NULL,'Soccer practice','','Field 3',0,'2026-09-29 20:00:00','2026-09-29 21:00:00','America/New_York',NULL,NULL,0,'FREQ=WEEKLY;BYDAY=TU,TH','[]','["2026-10-13T16:00:00"]','2026-09-29 20:00:00','9999-12-31 00:00:00','confirmed',NULL,'local',NULL,NULL,NULL,NULL,NULL,0,0,NULL,2,'00000000-0000-7000-8000-000000000001','2026-10-08 12:01:00','2026-10-08 12:05:00',NULL,0,0);
INSERT INTO "events" VALUES('00000000-0000-7000-8000-000000000502','00000000-0000-7000-8000-000000000401','00000000-0000-7000-8000-000000000501','2026-10-08T16:00:00','Soccer practice','','Field 3',0,'2026-10-08 21:00:00','2026-10-08 22:00:00','America/New_York',NULL,NULL,0,NULL,'[]','[]','2026-10-08 21:00:00','2026-10-08 22:00:00','confirmed',NULL,'local',NULL,NULL,NULL,NULL,NULL,0,0,NULL,1,'00000000-0000-7000-8000-000000000001','2026-10-08 12:05:00','2026-10-08 12:05:00',NULL,0,0);
INSERT INTO "events" VALUES('00000000-0000-7000-8000-000000000503','00000000-0000-7000-8000-000000000401',NULL,NULL,'Pajama day','','',1,NULL,NULL,NULL,'2026-10-09','2026-10-10',0,NULL,'[]','[]','2026-10-09 00:00:00','2026-10-11 00:00:00','confirmed','rose','local',NULL,NULL,NULL,NULL,NULL,0,0,NULL,1,'00000000-0000-7000-8000-000000000001','2026-10-08 12:02:00','2026-10-08 12:02:00',NULL,0,0);
INSERT INTO "events" VALUES('00000000-0000-7000-8000-000000000504','00000000-0000-7000-8000-000000000401',NULL,NULL,'Vet','','',0,'2026-10-07 13:00:00','2026-10-07 13:30:00','America/New_York',NULL,NULL,0,NULL,'[]','[]','2026-10-07 13:00:00','2026-10-07 13:30:00','confirmed',NULL,'local',NULL,NULL,NULL,NULL,NULL,0,0,NULL,2,'00000000-0000-7000-8000-000000000001','2026-10-08 12:03:00','2026-10-08 12:04:00','2026-10-08 12:04:00',0,0);
INSERT INTO "events" VALUES('00000000-0000-7000-8000-000000000505','00000000-0000-7000-8000-000000000402',NULL,NULL,'Field trip','','Sample Farm',0,'2026-10-15 13:00:00','2026-10-15 17:00:00','America/New_York',NULL,NULL,0,NULL,'[]','[]','2026-10-15 13:00:00','2026-10-15 17:00:00','confirmed',NULL,'sync','field-trip@school.example.com',NULL,NULL,'2026-10-08 17:00:00',0,0,0,NULL,1,NULL,'2026-10-08 18:00:00','2026-10-08 18:00:00',NULL,0,0);
CREATE TABLE "household" (
	id INTEGER NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	timezone VARCHAR(64), 
	week_starts_on INTEGER NOT NULL, 
	time_format VARCHAR(4) NOT NULL, 
	theme VARCHAR(8) NOT NULL, 
	daylight_tint BOOLEAN NOT NULL, 
	text_size VARCHAR(10) NOT NULL, 
	display_home_view VARCHAR(10) NOT NULL, 
	display_return_minutes INTEGER NOT NULL, 
	display_rail_side VARCHAR(8) NOT NULL, 
	display_controls_bottom BOOLEAN NOT NULL, 
	display_show_today_panel BOOLEAN NOT NULL, 
	display_orientation VARCHAR(10) NOT NULL, 
	display_sounds BOOLEAN NOT NULL, 
	display_dim_past BOOLEAN NOT NULL, 
	display_reduce_motion BOOLEAN NOT NULL, 
	sleep_from VARCHAR(5), 
	sleep_to VARCHAR(5), 
	sleep_mode VARCHAR(12) NOT NULL, 
	kid_safe_editing BOOLEAN NOT NULL, 
	parent_pin_hash VARCHAR(160), 
	pin_length INTEGER, 
	pin_updated_at DATETIME, 
	onboarded_at DATETIME, 
	location_label VARCHAR(120), 
	latitude FLOAT, 
	longitude FLOAT, 
	updated_at DATETIME NOT NULL, 
	default_calendar_id VARCHAR(36), 
	dim_from VARCHAR(5), 
	dim_level INTEGER DEFAULT '40' NOT NULL, 
	update_check BOOLEAN DEFAULT 0 NOT NULL, 
	display_week_layout VARCHAR(8) DEFAULT 'hours' NOT NULL, 
	show_tips BOOLEAN DEFAULT 1 NOT NULL, 
	display_rail_compact BOOLEAN DEFAULT 0 NOT NULL, 
	display_start VARCHAR(8) DEFAULT 'last' NOT NULL, 
	default_reminder_minutes INTEGER, 
	backups_enabled BOOLEAN DEFAULT 1 NOT NULL, 
	backups_keep_daily INTEGER DEFAULT '14' NOT NULL, 
	backups_keep_weekly INTEGER DEFAULT '8' NOT NULL, 
	CONSTRAINT pk_household PRIMARY KEY (id), 
	CONSTRAINT ck_household_single_row CHECK (id = 1), 
	CONSTRAINT fk_household_default_calendar_id_calendars FOREIGN KEY(default_calendar_id) REFERENCES calendars (id)
);
INSERT INTO "household" VALUES(1,'Sample Family','America/New_York',6,'12h','auto',1,'small','rolling',5,'left',0,1,'auto',0,1,0,NULL,NULL,'dim_clock',1,NULL,NULL,NULL,'2026-10-07 12:00:00','Sample Town',40.71,-74.01,'2026-10-07 12:00:00','01a1845c-5dee-71d3-b2b8-2454b532ceec','20:00',40,1,'hours',1,1,'home',NULL,1,21,4);
CREATE TABLE join_codes (
	code_hash VARCHAR(64) NOT NULL, 
	kind VARCHAR(8) NOT NULL, 
	created_by_device_id VARCHAR(36), 
	poll_token_hash VARCHAR(64), 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	used_at DATETIME, 
	used_by_device_id VARCHAR(36), 
	CONSTRAINT pk_join_codes PRIMARY KEY (code_hash), 
	CONSTRAINT fk_join_codes_created_by_device_id_devices FOREIGN KEY(created_by_device_id) REFERENCES devices (id) ON DELETE CASCADE, 
	CONSTRAINT fk_join_codes_used_by_device_id_devices FOREIGN KEY(used_by_device_id) REFERENCES devices (id) ON DELETE SET NULL
);
INSERT INTO "join_codes" VALUES('0000000000000000000000000000000000000000000000000000000000000002','kiosk',NULL,'0000000000000000000000000000000000000000000000000000000000000003','2026-10-07 12:09:00','2026-10-07 12:19:00','2026-10-07 12:10:00','00000000-0000-7000-8000-0000000000d2');
CREATE TABLE kiosk_panels (
	panel_key VARCHAR(64) NOT NULL, 
	position INTEGER NOT NULL, 
	visible BOOLEAN NOT NULL, 
	size VARCHAR(8) NOT NULL, 
	CONSTRAINT pk_kiosk_panels PRIMARY KEY (panel_key)
);
INSERT INTO "kiosk_panels" VALUES('calendar.today',0,1,'m');
CREATE TABLE list_items (
	id VARCHAR(36) NOT NULL, 
	list_id VARCHAR(36) NOT NULL, 
	text VARCHAR(200) NOT NULL, 
	note VARCHAR(500), 
	quantity VARCHAR(20), 
	due_date VARCHAR(10), 
	assigned_member_id VARCHAR(36), 
	checked_at DATETIME, 
	checked_by_member_id VARCHAR(36), 
	position INTEGER NOT NULL, 
	version INTEGER NOT NULL, 
	created_by_member_id VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	cleared_at DATETIME, 
	deleted_at DATETIME, 
	CONSTRAINT pk_list_items PRIMARY KEY (id), 
	CONSTRAINT fk_list_items_assigned_member_id_members FOREIGN KEY(assigned_member_id) REFERENCES members (id), 
	CONSTRAINT fk_list_items_checked_by_member_id_members FOREIGN KEY(checked_by_member_id) REFERENCES members (id), 
	CONSTRAINT fk_list_items_created_by_member_id_members FOREIGN KEY(created_by_member_id) REFERENCES members (id), 
	CONSTRAINT fk_list_items_list_id_lists FOREIGN KEY(list_id) REFERENCES lists (id)
);
INSERT INTO "list_items" VALUES('00000000-0000-7000-8000-000000000911','00000000-0000-7000-8000-000000000901','Milk',NULL,'2',NULL,NULL,NULL,NULL,0,1,'00000000-0000-7000-8000-000000000001','2026-10-08 19:01:00','2026-10-08 19:01:00',NULL,NULL);
INSERT INTO "list_items" VALUES('00000000-0000-7000-8000-000000000912','00000000-0000-7000-8000-000000000901','Bread','Whole wheat',NULL,NULL,NULL,'2026-10-08 19:10:00','00000000-0000-7000-8000-000000000002',1,2,'00000000-0000-7000-8000-000000000001','2026-10-08 19:01:00','2026-10-08 19:10:00',NULL,NULL);
INSERT INTO "list_items" VALUES('00000000-0000-7000-8000-000000000913','00000000-0000-7000-8000-000000000901','Apples',NULL,NULL,NULL,NULL,'2026-10-01 19:10:00','00000000-0000-7000-8000-000000000001',2,2,'00000000-0000-7000-8000-000000000001','2026-10-01 19:01:00','2026-10-01 19:10:00','2026-10-02 08:00:00',NULL);
INSERT INTO "list_items" VALUES('00000000-0000-7000-8000-000000000914','00000000-0000-7000-8000-000000000901','Call the plumber',NULL,NULL,'2026-10-09','00000000-0000-7000-8000-000000000001',NULL,NULL,3,1,'00000000-0000-7000-8000-000000000001','2026-10-08 19:02:00','2026-10-08 19:02:00',NULL,NULL);
INSERT INTO "list_items" VALUES('00000000-0000-7000-8000-000000000915','00000000-0000-7000-8000-000000000902','Tent',NULL,NULL,NULL,'00000000-0000-7000-8000-000000000002',NULL,NULL,0,1,'00000000-0000-7000-8000-000000000002','2026-10-08 19:00:00','2026-10-08 19:00:00',NULL,NULL);
CREATE TABLE lists (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	icon VARCHAR(32), 
	sort INTEGER NOT NULL, 
	created_by_member_id VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	deleted_at DATETIME, 
	CONSTRAINT pk_lists PRIMARY KEY (id), 
	CONSTRAINT fk_lists_created_by_member_id_members FOREIGN KEY(created_by_member_id) REFERENCES members (id)
);
INSERT INTO "lists" VALUES('00000000-0000-7000-8000-000000000901','Groceries','grocery',NULL,0,'00000000-0000-7000-8000-000000000001','2026-10-08 19:00:00','2026-10-08 19:00:00',NULL);
INSERT INTO "lists" VALUES('00000000-0000-7000-8000-000000000902','Packing: camping','packing',NULL,1,'00000000-0000-7000-8000-000000000002','2026-10-08 19:00:00','2026-10-08 19:30:00','2026-10-08 19:30:00');
CREATE TABLE meal_entries (
	id VARCHAR(36) NOT NULL, 
	day VARCHAR(10) NOT NULL, 
	slot VARCHAR(16) NOT NULL, 
	position INTEGER NOT NULL, 
	text VARCHAR(120) NOT NULL, 
	emoji VARCHAR(16), 
	recipe_url VARCHAR(500), 
	note VARCHAR(300), 
	member_id VARCHAR(36), 
	saved_meal_id VARCHAR(36), 
	source_url VARCHAR(500), 
	created_by_member_id VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	deleted_at DATETIME, 
	CONSTRAINT pk_meal_entries PRIMARY KEY (id), 
	CONSTRAINT fk_meal_entries_created_by_member_id_members FOREIGN KEY(created_by_member_id) REFERENCES members (id), 
	CONSTRAINT fk_meal_entries_member_id_members FOREIGN KEY(member_id) REFERENCES members (id), 
	CONSTRAINT fk_meal_entries_saved_meal_id_saved_meals FOREIGN KEY(saved_meal_id) REFERENCES saved_meals (id)
);
INSERT INTO "meal_entries" VALUES('00000000-0000-7000-8000-000000000b02','2026-10-08','dinner',0,'Tacos','🌮','https://recipes.example.com/tacos','Extra salsa','00000000-0000-7000-8000-000000000001','00000000-0000-7000-8000-000000000b01',NULL,'00000000-0000-7000-8000-000000000001','2026-10-08 21:00:00','2026-10-08 21:00:00',NULL);
INSERT INTO "meal_entries" VALUES('00000000-0000-7000-8000-000000000b03','2026-10-09','dinner',0,'Soup',NULL,NULL,NULL,NULL,NULL,NULL,'00000000-0000-7000-8000-000000000002','2026-10-08 21:05:00','2026-10-08 21:10:00','2026-10-08 21:10:00');
CREATE TABLE members (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(40) NOT NULL, 
	role VARCHAR(8) NOT NULL, 
	color VARCHAR(8) NOT NULL, 
	avatar_photo_id VARCHAR(36), 
	birthday VARCHAR(10), 
	sort INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	archived_at DATETIME, 
	CONSTRAINT pk_members PRIMARY KEY (id), 
	CONSTRAINT fk_members_avatar_photo_id_photos FOREIGN KEY(avatar_photo_id) REFERENCES photos (id) ON DELETE SET NULL
);
INSERT INTO "members" VALUES('00000000-0000-7000-8000-000000000001','Sample Parent','parent','sky','00000000-0000-7000-8000-000000000201',NULL,0,'2026-10-07 12:01:00',NULL);
INSERT INTO "members" VALUES('00000000-0000-7000-8000-000000000002','Sample Kid','kid','berry',NULL,'2018-05-04',1,'2026-10-07 12:02:00',NULL);
INSERT INTO "members" VALUES('00000000-0000-7000-8000-000000000003','Sample Guest','parent','moss',NULL,NULL,2,'2026-10-07 12:03:00','2026-10-07 13:00:00');
CREATE TABLE network_allowlist (
	id VARCHAR(36) NOT NULL, 
	target VARCHAR(255) NOT NULL, 
	label VARCHAR(80) NOT NULL, 
	created_by_member_id VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	CONSTRAINT pk_network_allowlist PRIMARY KEY (id), 
	CONSTRAINT fk_network_allowlist_created_by_member_id_members FOREIGN KEY(created_by_member_id) REFERENCES members (id) ON DELETE SET NULL
);
INSERT INTO "network_allowlist" VALUES('00000000-0000-7000-8000-000000000301','192.168.1.20/32','Sample NAS','00000000-0000-7000-8000-000000000001','2026-10-07 12:20:00');
CREATE TABLE oauth_states (
	state_hash VARCHAR(64) NOT NULL, 
	provider VARCHAR(16) NOT NULL, 
	code_verifier VARCHAR(128) NOT NULL, 
	device_id VARCHAR(36), 
	account_id VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	used_at DATETIME, 
	CONSTRAINT pk_oauth_states PRIMARY KEY (state_hash)
);
INSERT INTO "oauth_states" VALUES('0000000000000000000000000000000000000000000000000000000000000004','google','sample-verifier','00000000-0000-7000-8000-0000000000d1',NULL,'2026-10-08 18:40:00','2026-10-08 18:50:00',NULL);
CREATE TABLE photo_source_items (
	id VARCHAR(36) NOT NULL, 
	source_id VARCHAR(36) NOT NULL, 
	remote_id VARCHAR(100) NOT NULL, 
	photo_id VARCHAR(36), 
	taken_at DATETIME, 
	seen_at DATETIME NOT NULL, 
	fetched_at DATETIME, 
	dropped_at DATETIME, 
	fetch_failures INTEGER DEFAULT '0' NOT NULL, 
	CONSTRAINT pk_photo_source_items PRIMARY KEY (id), 
	CONSTRAINT fk_photo_source_items_source_id_photo_sources FOREIGN KEY(source_id) REFERENCES photo_sources (id), 
	CONSTRAINT uq_photo_source_items_source_id UNIQUE (source_id, remote_id)
);
INSERT INTO "photo_source_items" VALUES('00000000-0000-7000-8000-000000000b24','00000000-0000-7000-8000-000000000b22','r-1','00000000-0000-7000-8000-000000000b23','2026-07-04 15:00:00','2026-10-21 17:00:00','2026-10-21 16:01:00',NULL,0);
INSERT INTO "photo_source_items" VALUES('00000000-0000-7000-8000-000000000b25','00000000-0000-7000-8000-000000000b22','r-2',NULL,'2026-06-01 12:00:00','2026-10-21 17:00:00',NULL,NULL,1);
CREATE TABLE photo_sources (
	id VARCHAR(36) NOT NULL, 
	kind VARCHAR(12) NOT NULL, 
	label VARCHAR(80) NOT NULL, 
	config_json TEXT NOT NULL, 
	credentials_enc TEXT, 
	allow_private BOOLEAN NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	last_scan_at DATETIME, 
	last_error VARCHAR(300), 
	items_seen INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	deleted_at DATETIME, status VARCHAR(20) DEFAULT 'connected' NOT NULL, options_json TEXT DEFAULT '{}' NOT NULL, options_at DATETIME, 
	CONSTRAINT pk_photo_sources PRIMARY KEY (id)
);
INSERT INTO "photo_sources" VALUES('00000000-0000-7000-8000-000000000b21','inbox','Photos folder','{}',NULL,0,1,'2026-10-08 21:30:00',NULL,1,'2026-10-08 21:00:00',NULL,'connected','{}',NULL);
INSERT INTO "photo_sources" VALUES('00000000-0000-7000-8000-000000000b22','immich','Immich','{"url": "http://immich.test", "picks": {"people": ["p-mia"], "albums": [], "tags": []}, "limit": 500}',NULL,0,1,'2026-10-21 17:00:00','Sunroom can''t read this library''s saved key any more. Connect it again.',1,'2026-10-21 16:00:00',NULL,'needs_reconnect','{"people": [{"id": "p-mia", "name": "Sample Kid", "count": null, "has_thumb": true}], "albums": [{"id": "a-beach", "name": "Beach 2026", "count": 2, "has_thumb": true}], "tags": [], "unnamed_people": 1}','2026-10-21 16:00:00');
CREATE TABLE photos (
	id VARCHAR(36) NOT NULL, 
	kind VARCHAR(8) NOT NULL, 
	source_key VARCHAR(64) NOT NULL, 
	original_name VARCHAR(255), 
	taken_at DATETIME, 
	width INTEGER NOT NULL, 
	height INTEGER NOT NULL, 
	bytes INTEGER NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	hidden BOOLEAN NOT NULL, 
	deleted_at DATETIME, 
	CONSTRAINT pk_photos PRIMARY KEY (id), 
	CONSTRAINT uq_photos_kind_sha256 UNIQUE (kind, sha256)
);
INSERT INTO "photos" VALUES('00000000-0000-7000-8000-000000000201','avatar','upload','sample.jpg',NULL,512,512,2048,'0000000000000000000000000000000000000000000000000000000000000001','2026-10-07 12:05:00',0,NULL);
INSERT INTO "photos" VALUES('00000000-0000-7000-8000-000000000b23','library','source:00000000-0000-7000-8000-000000000b22','r-1.jpg','2026-07-04 15:00:00',1440,960,4096,'0000000000000000000000000000000000000000000000000000000000000002','2026-10-21 16:01:00',0,NULL);
CREATE TABLE plugin_state (
	plugin_id VARCHAR(32) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	settings_json TEXT NOT NULL, 
	settings_version INTEGER NOT NULL, 
	plugin_version VARCHAR(16) NOT NULL, 
	enabled_at DATETIME, 
	disabled_at DATETIME, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_plugin_state PRIMARY KEY (plugin_id)
);
INSERT INTO "plugin_state" VALUES('sample',0,'{}',1,'1.0.0',NULL,NULL,'2026-10-07 12:00:00');
INSERT INTO "plugin_state" VALUES('calendar_sync',1,'{"google_client_id": null, "google_client_secret": null}',1,'1.0.0','2026-10-08 18:00:00',NULL,'2026-10-08 18:00:00');
INSERT INTO "plugin_state" VALUES('lists',1,'{"auto_clear_days": "never"}',1,'1.0.0','2026-10-08 19:00:00',NULL,'2026-10-08 19:00:00');
INSERT INTO "plugin_state" VALUES('chores',1,'{"stars": true, "rewards": true, "routines": true, "approval": false}',2,'1.0.0','2026-10-08 19:00:00',NULL,'2026-10-08 19:05:00');
INSERT INTO "plugin_state" VALUES('meals',1,'{"slots": ["dinner"], "calendar_slots": ["dinner"]}',2,'1.1.0','2026-10-08 21:00:00',NULL,'2026-10-08 21:00:00');
INSERT INTO "plugin_state" VALUES('countdowns',1,'{"birthdays": true}',1,'1.0.0','2026-10-08 21:00:00',NULL,'2026-10-08 21:00:00');
INSERT INTO "plugin_state" VALUES('screensaver',1,'{"start_after": "15", "every": "30", "show_clock": true, "shuffle": true}',1,'1.0.0','2026-10-08 21:00:00',NULL,'2026-10-08 21:00:00');
INSERT INTO "plugin_state" VALUES('weather',0,'{"units": "auto"}',1,'1.0.0',NULL,'2026-10-08 21:40:00','2026-10-08 21:40:00');
CREATE TABLE point_adjustments (
	id VARCHAR(36) NOT NULL, 
	member_id VARCHAR(36) NOT NULL, 
	points INTEGER NOT NULL, 
	reason VARCHAR(120) NOT NULL, 
	by_member_id VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	CONSTRAINT pk_point_adjustments PRIMARY KEY (id), 
	CONSTRAINT fk_point_adjustments_by_member_id_members FOREIGN KEY(by_member_id) REFERENCES members (id), 
	CONSTRAINT fk_point_adjustments_member_id_members FOREIGN KEY(member_id) REFERENCES members (id)
);
INSERT INTO "point_adjustments" VALUES('00000000-0000-7000-8000-000000000a41','00000000-0000-7000-8000-000000000002',10,'Helped with the groceries','00000000-0000-7000-8000-000000000001','2026-10-06 18:00:00');
CREATE TABLE redemptions (
	id VARCHAR(36) NOT NULL, 
	reward_id VARCHAR(36) NOT NULL, 
	member_id VARCHAR(36) NOT NULL, 
	cost_points INTEGER NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	requested_at DATETIME NOT NULL, 
	decided_by_member_id VARCHAR(36), 
	decided_at DATETIME, 
	CONSTRAINT pk_redemptions PRIMARY KEY (id), 
	CONSTRAINT fk_redemptions_decided_by_member_id_members FOREIGN KEY(decided_by_member_id) REFERENCES members (id), 
	CONSTRAINT fk_redemptions_member_id_members FOREIGN KEY(member_id) REFERENCES members (id), 
	CONSTRAINT fk_redemptions_reward_id_rewards FOREIGN KEY(reward_id) REFERENCES rewards (id)
);
INSERT INTO "redemptions" VALUES('00000000-0000-7000-8000-000000000a51','00000000-0000-7000-8000-000000000a11','00000000-0000-7000-8000-000000000002',30,'requested','2026-10-08 20:00:00',NULL,NULL);
CREATE TABLE remote_calendars (
	id VARCHAR(36) NOT NULL, 
	account_id VARCHAR(36) NOT NULL, 
	remote_id VARCHAR(500) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	color_hint VARCHAR(9), 
	read_only BOOLEAN NOT NULL, 
	mapped BOOLEAN NOT NULL, 
	calendar_id VARCHAR(36), 
	sync_token TEXT, 
	ctag VARCHAR(200), 
	last_synced_at DATETIME, 
	last_error VARCHAR(300), 
	created_at DATETIME NOT NULL, 
	CONSTRAINT pk_remote_calendars PRIMARY KEY (id), 
	CONSTRAINT fk_remote_calendars_account_id_sync_accounts FOREIGN KEY(account_id) REFERENCES sync_accounts (id), 
	CONSTRAINT fk_remote_calendars_calendar_id_calendars FOREIGN KEY(calendar_id) REFERENCES calendars (id), 
	CONSTRAINT uq_remote_calendars_account_id UNIQUE (account_id, remote_id)
);
INSERT INTO "remote_calendars" VALUES('00000000-0000-7000-8000-000000000702','00000000-0000-7000-8000-000000000701','feed-000000000000000000000001','School',NULL,1,1,'00000000-0000-7000-8000-000000000402','{"etag": "\"1\""}',NULL,'2026-10-08 18:30:00',NULL,'2026-10-08 18:00:00');
CREATE TABLE rewards (
	id VARCHAR(36) NOT NULL, 
	title VARCHAR(80) NOT NULL, 
	cost_points INTEGER NOT NULL, 
	icon VARCHAR(32), 
	active BOOLEAN NOT NULL, 
	sort INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	deleted_at DATETIME, 
	CONSTRAINT pk_rewards PRIMARY KEY (id)
);
INSERT INTO "rewards" VALUES('00000000-0000-7000-8000-000000000a11','Movie night',30,'film',1,0,'2026-10-01 12:00:00',NULL);
CREATE TABLE routine_checks (
	routine_step_id VARCHAR(36) NOT NULL, 
	member_id VARCHAR(36) NOT NULL, 
	day VARCHAR(10) NOT NULL, 
	checked_at DATETIME NOT NULL, 
	CONSTRAINT pk_routine_checks PRIMARY KEY (routine_step_id, member_id, day), 
	CONSTRAINT fk_routine_checks_member_id_members FOREIGN KEY(member_id) REFERENCES members (id), 
	CONSTRAINT fk_routine_checks_routine_step_id_routine_steps FOREIGN KEY(routine_step_id) REFERENCES routine_steps (id)
);
INSERT INTO "routine_checks" VALUES('00000000-0000-7000-8000-000000000a22','00000000-0000-7000-8000-000000000002','2026-10-08','2026-10-08 23:35:00');
CREATE TABLE routine_finishes (
	routine_id VARCHAR(36) NOT NULL, 
	member_id VARCHAR(36) NOT NULL, 
	day VARCHAR(10) NOT NULL, 
	finished_at DATETIME NOT NULL, 
	points_awarded INTEGER NOT NULL, 
	CONSTRAINT pk_routine_finishes PRIMARY KEY (routine_id, member_id, day), 
	CONSTRAINT fk_routine_finishes_member_id_members FOREIGN KEY(member_id) REFERENCES members (id), 
	CONSTRAINT fk_routine_finishes_routine_id_routines FOREIGN KEY(routine_id) REFERENCES routines (id)
);
INSERT INTO "routine_finishes" VALUES('00000000-0000-7000-8000-000000000a21','00000000-0000-7000-8000-000000000002','2026-10-07','2026-10-07 23:50:00',3);
CREATE TABLE routine_steps (
	id VARCHAR(36) NOT NULL, 
	routine_id VARCHAR(36) NOT NULL, 
	title VARCHAR(80) NOT NULL, 
	icon VARCHAR(32), 
	position INTEGER NOT NULL, 
	CONSTRAINT pk_routine_steps PRIMARY KEY (id), 
	CONSTRAINT fk_routine_steps_routine_id_routines FOREIGN KEY(routine_id) REFERENCES routines (id)
);
INSERT INTO "routine_steps" VALUES('00000000-0000-7000-8000-000000000a22','00000000-0000-7000-8000-000000000a21','Brush teeth','toothbrush',0);
INSERT INTO "routine_steps" VALUES('00000000-0000-7000-8000-000000000a23','00000000-0000-7000-8000-000000000a21','Into bed','bed',1);
CREATE TABLE routines (
	id VARCHAR(36) NOT NULL, 
	title VARCHAR(80) NOT NULL, 
	member_id VARCHAR(36), 
	days_json TEXT NOT NULL, 
	window_start VARCHAR(5) NOT NULL, 
	window_end VARCHAR(5) NOT NULL, 
	icon VARCHAR(32), 
	points INTEGER NOT NULL, 
	sort INTEGER NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	deleted_at DATETIME, 
	CONSTRAINT pk_routines PRIMARY KEY (id), 
	CONSTRAINT fk_routines_member_id_members FOREIGN KEY(member_id) REFERENCES members (id)
);
INSERT INTO "routines" VALUES('00000000-0000-7000-8000-000000000a21','Bedtime routine','00000000-0000-7000-8000-000000000002','[0, 1, 2, 3, 4, 5, 6]','19:30','20:30','moon',3,0,1,'2026-10-01 12:00:00',NULL);
CREATE TABLE saved_meals (
	id VARCHAR(36) NOT NULL, 
	text VARCHAR(120) NOT NULL, 
	emoji VARCHAR(16), 
	recipe_url VARCHAR(500), 
	ingredients_json TEXT NOT NULL, 
	use_count INTEGER NOT NULL, 
	last_used_at DATETIME, 
	created_by_member_id VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	deleted_at DATETIME, 
	CONSTRAINT pk_saved_meals PRIMARY KEY (id), 
	CONSTRAINT fk_saved_meals_created_by_member_id_members FOREIGN KEY(created_by_member_id) REFERENCES members (id)
);
INSERT INTO "saved_meals" VALUES('00000000-0000-7000-8000-000000000b01','Tacos','🌮','https://recipes.example.com/tacos','["Tortillas", "Cheese"]',3,'2026-10-08 21:00:00','00000000-0000-7000-8000-000000000001','2026-10-01 21:00:00','2026-10-08 21:00:00',NULL);
CREATE TABLE sync_accounts (
	id VARCHAR(36) NOT NULL, 
	provider VARCHAR(16) NOT NULL, 
	auth_mode VARCHAR(16) NOT NULL, 
	label VARCHAR(120) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	server_url VARCHAR(500), 
	username VARCHAR(200), 
	credentials_enc TEXT, 
	config_json TEXT NOT NULL, 
	allow_private BOOLEAN NOT NULL, 
	owner_member_id VARCHAR(36), 
	interval_s INTEGER NOT NULL, 
	last_sync_at DATETIME, 
	last_success_at DATETIME, 
	next_sync_at DATETIME, 
	last_error VARCHAR(300), 
	last_error_at DATETIME, 
	consecutive_failures INTEGER NOT NULL, 
	version INTEGER NOT NULL, 
	created_by_member_id VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	deleted_at DATETIME, 
	CONSTRAINT pk_sync_accounts PRIMARY KEY (id), 
	CONSTRAINT fk_sync_accounts_created_by_member_id_members FOREIGN KEY(created_by_member_id) REFERENCES members (id), 
	CONSTRAINT fk_sync_accounts_owner_member_id_members FOREIGN KEY(owner_member_id) REFERENCES members (id)
);
INSERT INTO "sync_accounts" VALUES('00000000-0000-7000-8000-000000000701','ics','none','School','connected','school.example.com/school.ics',NULL,'sample-ciphertext','{}',0,'00000000-0000-7000-8000-000000000002',1800,'2026-10-08 18:30:00','2026-10-08 18:30:00','2026-10-08 19:00:00',NULL,NULL,0,1,'00000000-0000-7000-8000-000000000001','2026-10-08 18:00:00',NULL);
INSERT INTO "sync_accounts" VALUES('00000000-0000-7000-8000-000000000a21','caldav','app_password','Apple · sample@…','connected','https://caldav.icloud.com','sample@example.com','sample-ciphertext','{}',0,NULL,300,'2026-10-13 19:30:00','2026-10-13 19:30:00','2026-10-13 19:35:00',NULL,NULL,0,1,'00000000-0000-7000-8000-000000000001','2026-10-13 19:20:00',NULL);
CREATE TABLE sync_runs (
	id VARCHAR(36) NOT NULL, 
	account_id VARCHAR(36) NOT NULL, 
	started_at DATETIME NOT NULL, 
	finished_at DATETIME, 
	outcome VARCHAR(16) NOT NULL, 
	fetched INTEGER NOT NULL, 
	created INTEGER NOT NULL, 
	updated INTEGER NOT NULL, 
	deleted INTEGER NOT NULL, 
	pushed INTEGER NOT NULL, 
	error VARCHAR(300), 
	duration_ms INTEGER, 
	CONSTRAINT pk_sync_runs PRIMARY KEY (id), 
	CONSTRAINT fk_sync_runs_account_id_sync_accounts FOREIGN KEY(account_id) REFERENCES sync_accounts (id)
);
INSERT INTO "sync_runs" VALUES('00000000-0000-7000-8000-000000000801','00000000-0000-7000-8000-000000000701','2026-10-08 18:30:00','2026-10-08 18:30:01','ok',1,0,0,0,0,NULL,140);
CREATE TABLE weather_cache (
	id INTEGER NOT NULL, 
	latitude FLOAT NOT NULL, 
	longitude FLOAT NOT NULL, 
	units VARCHAR(12) NOT NULL, 
	payload_json TEXT, 
	fetched_at DATETIME, 
	expires_at DATETIME, 
	last_error VARCHAR(300), 
	last_error_at DATETIME, 
	CONSTRAINT pk_weather_cache PRIMARY KEY (id), 
	CONSTRAINT ck_weather_cache_one_row CHECK (id = 1)
);
INSERT INTO "weather_cache" VALUES(1,40.71,-74.01,'fahrenheit','{"current": {"time": "2026-10-08T17:00", "temperature_2m": 61.0, "weather_code": 2, "is_day": 1}}','2026-10-08 21:00:00','2026-10-08 22:00:00',NULL,NULL);
CREATE INDEX ix_join_codes_created_by_device_id ON join_codes (created_by_device_id);
CREATE INDEX ix_join_codes_expires_at ON join_codes (expires_at);
CREATE INDEX ix_join_codes_poll_token_hash ON join_codes (poll_token_hash);
CREATE INDEX ix_event_revisions_created_at ON event_revisions (created_at);
CREATE INDEX ix_event_revisions_series_id ON event_revisions (series_id);
CREATE INDEX ix_remote_calendars_account_id ON remote_calendars (account_id);
CREATE INDEX ix_sync_runs_account_id ON sync_runs (account_id);
CREATE INDEX ix_list_items_due_date ON list_items (due_date);
CREATE INDEX ix_list_items_list_id ON list_items (list_id);
CREATE INDEX ix_point_adjustments_member_id ON point_adjustments (member_id);
CREATE INDEX ix_redemptions_member_id ON redemptions (member_id);
CREATE INDEX ix_redemptions_reward_id ON redemptions (reward_id);
CREATE INDEX ix_chore_completions_chore_id ON chore_completions (chore_id);
CREATE INDEX ix_chore_completions_due_date ON chore_completions (due_date);
CREATE INDEX ix_routine_steps_routine_id ON routine_steps (routine_id);
CREATE INDEX ix_meal_entries_day ON meal_entries (day);
CREATE UNIQUE INDEX uq_meal_entries_spot ON meal_entries (day, slot, position) WHERE deleted_at IS NULL;
CREATE INDEX ix_countdowns_date ON countdowns (date);
CREATE INDEX ix_events_range ON events (calendar_id, window_start_utc, window_end_utc);
CREATE INDEX ix_events_parent_event_id ON events (parent_event_id);
CREATE INDEX ix_photo_source_items_source_id ON photo_source_items (source_id);
COMMIT;
