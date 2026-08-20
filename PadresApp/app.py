import streamlit as st
import statsapi
import feedparser
import pandas as pd
import random
import requests
import pybaseball as pyb
import unicodedata
from datetime import datetime, timedelta
from collections import Counter, defaultdict

# ==========================================
# 1. PAGE CONFIGURATION & LAYOUT
# ==========================================
st.set_page_config(
    page_title="Padres Command Center", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

# ==========================================
# 2. SAFE CASTING & UTILITY HELPERS
# ==========================================
def safe_int(val, default=0):
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default

def safe_float(val, default=0.0):
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default

def clean_player_name(name):
    """Strips accent marks for clean API name lookups."""
    if not name: return ""
    return unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('utf-8')

def get_game_topics(game):
    """Generates dynamic radio talking points based on game results."""
    is_padres_home = "Padres" in game['home_name']
    padres_score = game['home_score'] if is_padres_home else game['away_score']
    opp_score = game['away_score'] if is_padres_home else game['home_score']
    opp_name = game['away_name'] if is_padres_home else game['home_name']
    
    diff = padres_score - opp_score
    topics = []
    
    if diff > 0:
        if diff >= 4:
            topics.append(f"🔥 **Offensive Explosion:** The bats came alive to hang {padres_score} runs on {opp_name}. Turning point or flash in the pan?")
        else:
            topics.append(f"😅 **Nail-Biter Win:** A tight {padres_score}-{opp_score} victory. Are we relying too heavily on the bullpen?")
    else:
        if diff <= -4:
            topics.append(f"📉 **Ugly Loss:** Dropping this one by {abs(diff)} runs. Does a blowout expose rotation depth?")
        else:
            topics.append(f"💔 **Heartbreaker:** Falling short {opp_score}-{padres_score}. Critical margins for Wild Card positioning.")
            
    wp = game.get('winning_pitcher', 'the starter')
    lp = game.get('losing_pitcher', 'the starter')
    if diff > 0:
        topics.append(f"⚾ **Pitching Praise:** Credit to {wp} for the win. Solidifying his role going forward?")
    else:
        topics.append(f"⚾ **Mound Struggles:** {lp} took the loss. How short is the starting rotation leash?")
        
    topics.append("🎙️ **Caller Prompt:** What is the ONE glaring hole this team needs to fix before the Trade Deadline?")
    return topics

TRIVIA_BANK = [
    {"q": "Who threw the very first no-hitter in Padres history?", "a": "Joe Musgrove (April 9, 2021 vs. Rangers)"},
    {"q": "What two years did the Padres win the NL Pennant?", "a": "1984 and 1998"},
    {"q": "Padres all-time franchise leader in home runs?", "a": "Manny Machado"}
]

# ==========================================
# 3. CACHED API & DATA ENGINE
# ==========================================
@st.cache_data(ttl=3600)
def get_full_standings(league_id):
    """Fetches division standings formatted into clean DataFrames."""
    standings_dict = {}
    try:
        raw_standings = statsapi.standings_data(leagueId=league_id)
        for div_id, div_data in raw_standings.items():
            div_name = div_data.get('div_name', f"Division {div_id}")
            team_list = []
            for team in div_data.get('teams', []):
                pct_str = f"{team['w'] / (team['w'] + team['l']):.3f}" if (team['w'] + team['l']) > 0 else ".000"
                gb = team.get('gb', '—')
                if gb == 0 or gb == 0.0: gb = '—'
                team_list.append({
                    "Rank": team.get('div_rank', '—'),
                    "Team": team.get('name', '—'),
                    "W": team.get('w', 0),
                    "L": team.get('l', 0),
                    "PCT": pct_str,
                    "GB": gb,
                    "_id": team.get('team_id') or team.get('id')
                })
            standings_dict[div_name] = pd.DataFrame(team_list)
    except Exception:
        pass
    return standings_dict

@st.cache_data(ttl=3600)
def get_wildcard_standings(league_id):
    """Computes Wild Card race standings for a given league ID (104=NL, 103=AL) with last game results."""
    try:
        two_days_ago = (datetime.now() - timedelta(days=2)).strftime("%m/%d/%Y")
        today_str = datetime.now().strftime("%m/%d/%Y")
        recent_games = statsapi.schedule(start_date=two_days_ago, end_date=today_str)
        
        last_game_map = {}
        for g in recent_games:
            if g.get('status') == 'Final':
                away_id, home_id = g.get('away_id'), g.get('home_id')
                away_name, home_name = g.get('away_name', ''), g.get('home_name', '')
                a_score, h_score = safe_int(g.get('away_score')), safe_int(g.get('home_score'))
                
                if a_score > h_score:
                    res_away = f"🟢 W {a_score}-{h_score}"
                    res_home = f"🔴 L {h_score}-{a_score}"
                else:
                    res_away = f"🔴 L {a_score}-{h_score}"
                    res_home = f"🟢 W {h_score}-{a_score}"
                    
                if away_id: last_game_map[away_id] = res_away
                if home_id: last_game_map[home_id] = res_home
                if away_name: last_game_map[away_name] = res_away
                if home_name: last_game_map[home_name] = res_home

        standings = statsapi.standings_data(leagueId=league_id)
        all_teams = []
        for div_id, div_data in standings.items():
            for team in div_data.get('teams', []):
                w, l = team['w'], team['l']
                pct = w / (w + l) if (w + l) > 0 else 0.0
                t_id = team.get('team_id') or team.get('id')
                all_teams.append({
                    'name': team['name'],
                    'w': w,
                    'l': l,
                    'pct': pct,
                    'div_rank': int(team.get('div_rank', 99)),
                    'team_id': t_id
                })
        
        wc_teams = [t for t in all_teams if t['div_rank'] > 1]
        wc_teams.sort(key=lambda x: x['pct'], reverse=True)
        
        if len(wc_teams) < 3:
            return pd.DataFrame()
            
        benchmark = wc_teams[2]
        rows = []
        for i, team in enumerate(wc_teams[:8]):
            gb_val = ((benchmark['w'] - team['w']) + (team['l'] - benchmark['l'])) / 2.0
            if i < 3:
                gb_str = f"+{abs(gb_val)}" if gb_val < 0 else "—"
                rank_str = f"WC #{i+1} 🔒"
            else:
                gb_str = f"-{gb_val}" if gb_val > 0 else "—"
                rank_str = f"#{i+1}"
                
            pct_str = f"{team['pct']:.3f}".replace("0.", ".")
            last_res = last_game_map.get(team['team_id'], last_game_map.get(team['name'], "—"))
            
            rows.append({
                "Rank": rank_str,
                "Team": team['name'],
                "W": team['w'],
                "L": team['l'],
                "PCT": pct_str,
                "GB": gb_str,
                "Last Game": last_res
            })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_padres_wc_hub_data():
    """Fetches Padres Wild Card status, yesterday's result indicator, and Wild Card standings."""
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%m/%d/%Y")
    y_status_label = "No Game Yesterday"
    y_delta_str = "Off Day"
    y_color = "off"
    
    try:
        y_games = statsapi.schedule(team=135, date=yesterday_str)
        if y_games and y_games[0].get('status') == 'Final':
            g = y_games[0]
            is_home = "Padres" in g['home_name']
            p_score = g['home_score'] if is_home else g['away_score']
            opp_score = g['away_score'] if is_home else g['home_score']
            opp_name = g['away_name'] if is_home else g['home_name']
            opp_short = opp_name.split()[-1]
            
            if p_score > opp_score:
                y_status_label = "⬆️ WON"
                y_delta_str = f"{p_score}-{opp_score} vs {opp_short}"
                y_color = "normal"
            else:
                y_status_label = "⬇️ LOST"
                y_delta_str = f"{p_score}-{opp_score} vs {opp_short}"
                y_color = "inverse"
    except Exception:
        pass

    wc_df = get_wildcard_standings(104)
    padres_row = {}
    if not wc_df.empty:
        p_matches = wc_df[wc_df['Team'].str.contains('Padres', case=False)]
        if not p_matches.empty:
            padres_row = p_matches.iloc[0].to_dict()

    return y_status_label, y_delta_str, y_color, wc_df, padres_row

@st.cache_data(ttl=14400)
def get_clean_leaders(stat_type, stat_group, season, league_id=None):
    """Parses statsapi.league_leaders output into a structured DataFrame. league_id: 103=AL, 104=NL, None=MLB-wide."""
    try:
        kwargs = {'statGroup': stat_group, 'limit': 5, 'season': season}
        if league_id:
            kwargs['leagueId'] = league_id
        raw = statsapi.league_leaders(stat_type, **kwargs)
        lines = [l.strip() for l in raw.split('\n') if l.strip()]
        if len(lines) <= 1:
            return pd.DataFrame()
        rows = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 4:
                rank = parts[0]
                val = parts[-1]
                player_team = " ".join(parts[1:-1])
                rows.append({
                    "Rank": rank,
                    "Player & Team": player_team,
                    "Value": val
                })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=43200)
def get_padres_roster_map(year):
    """Generates mapping of active Padres hitters (ID -> Full Name)."""
    padres_map = {}
    try:
        roster_data = statsapi.get('team_roster', {'teamId': 135})
        for player in roster_data.get('roster', []):
            pos = player.get('position', {}).get('abbreviation', '')
            if pos != 'P':
                pid = player.get('person', {}).get('id')
                pname = player.get('person', {}).get('fullName')
                if pid and pname:
                    padres_map[pid] = pname
    except Exception:
        pass
        
    if not padres_map:
        try:
            params = {'season': year, 'stats': 'season', 'group': 'hitting', 'teamId': 135}
            raw_stats = statsapi.get('stats', params)
            for stat_record in raw_stats.get('stats', []):
                for split in stat_record.get('splits', []):
                    pid = split['player']['id']
                    pname = split['player']['fullName']
                    padres_map[pid] = pname
        except Exception:
            pass
    return padres_map

@st.cache_data(ttl=43200)
def get_bvp_matchups(opp_id, padres_ids, padres_map):
    """Fetches career statistics for Padres hitters vs opposing pitcher."""
    bvp_list = []
    if not padres_ids: return bvp_list
    id_string = ",".join([str(pid) for pid in padres_ids])
    try:
        res = statsapi.get('people', {
            'personIds': id_string, 
            'hydrate': f'stats(group=[hitting],type=[vsPlayerTotal],opposingPlayerId={opp_id})'
        })
        for person in res.get('people', []):
            hitter_name = person.get('fullName', 'Unknown')
            for stat_record in person.get('stats', []):
                for split in stat_record.get('splits', []):
                    s = split.get('stat', {})
                    ab = s.get('atBats', 0)
                    if ab > 0:
                        bvp_list.append({
                            'Hitter': hitter_name,
                            'AB': ab,
                            'H': s.get('hits', 0),
                            'HR': s.get('homeRuns', 0),
                            'RBI': s.get('rbi', 0),
                            'AVG': s.get('avg', '.000'),
                            'OPS': s.get('ops', '.000')
                        })
    except Exception:
        pass
    return bvp_list

@st.cache_data(ttl=14400)
def calculate_ai_projections(year):
    """Calculates 162-game AI pace projections for team record and star players."""
    try:
        record = statsapi.get('standings', {'leagueId': 104, 'season': year})
        sd_wins, sd_losses = 0, 0
        for rec in record.get('records', []):
            for t in rec.get('teamRecords', []):
                if t.get('team', {}).get('id') == 135:
                    sd_wins = t.get('wins', 0)
                    sd_losses = t.get('losses', 0)
                    break
        
        total_played = sd_wins + sd_losses
        games_remaining = max(162 - total_played, 0)
        win_pct = sd_wins / total_played if total_played > 0 else 0.500
        proj_wins = round(sd_wins + (win_pct * games_remaining))
        
        hitter_projections = []
        for name in ["Manny Machado", "Fernando Tatis Jr.", "Jackson Merrill"]:
            lookup = statsapi.lookup_player(name)
            if lookup:
                pid = lookup[0]['id']
                pstats = statsapi.player_stat_data(pid, group="hitting", type="season")
                if pstats and 'stats' in pstats and len(pstats['stats']) > 0:
                    s = pstats['stats'][0]['stats']
                    gp = s.get('gamesPlayed', 1)
                    hr, rbi = s.get('homeRuns', 0), s.get('rbi', s.get('runsBattedIn', 0))
                    pace_factor = (games_remaining / max(total_played, 1)) * 0.95
                    hitter_projections.append({
                        "Player": name, "Games": gp, "Current HR": hr,
                        "🤖 Proj HR": round(hr + (hr * pace_factor)),
                        "Current RBI": rbi, "🤖 Proj RBI": round(rbi + (rbi * pace_factor))
                    })

        pitcher_projections = []
        miller_lookup = statsapi.lookup_player("Mason Miller")
        if miller_lookup:
            pid = miller_lookup[0]['id']
            pstats = statsapi.player_stat_data(pid, group="pitching", type="season")
            if pstats and 'stats' in pstats and len(pstats['stats']) > 0:
                s = pstats['stats'][0]['stats']
                gp = s.get('gamesPitched', s.get('gamesPlayed', 1))
                so, sv = s.get('strikeOuts', 0), s.get('saves', 0)
                pace_factor = (games_remaining / max(total_played, 1)) * 0.95
                pitcher_projections.append({
                    "Player": "Mason Miller", "Appearances": gp, "Current K": so,
                    "🤖 Proj K": round(so + (so * pace_factor)),
                    "Current Saves": sv, "🤖 Proj Saves": round(sv + (sv * pace_factor))
                })
                    
        return {
            "team_wins": proj_wins, "team_losses": 162 - proj_wins,
            "current_wins": sd_wins, "current_losses": sd_losses,
            "hitters": hitter_projections, "pitchers": pitcher_projections
        }
    except Exception:
        return None

@st.cache_data(ttl=3600)
def get_injury_report(team_id):
    """Fetches current Injured List players from the 40-man roster."""
    il_players = []
    try:
        roster_data = statsapi.get('team_roster', {'teamId': team_id, 'rosterType': '40Man'})
        for p in roster_data.get('roster', []):
            status = p.get('status', {})
            code = status.get('code', '')
            if code.startswith('D'):
                person = p.get('person', {})
                il_players.append({
                    'Player': person.get('fullName', 'Unknown'),
                    'Pos': p.get('position', {}).get('abbreviation', ''),
                    'Status': status.get('description', code),
                    'Note': p.get('note', '') or '—'
                })
    except Exception:
        pass
    return il_players

@st.cache_data(ttl=3600)
def get_recent_transactions(team_id, days=10):
    """Fetches recent roster transactions (IL moves, call-ups, DFAs, signings)."""
    try:
        end = datetime.now()
        start = end - timedelta(days=days)
        data = statsapi.get('transactions', {
            'teamId': team_id,
            'startDate': start.strftime('%m/%d/%Y'),
            'endDate': end.strftime('%m/%d/%Y')
        })
        moves = []
        for t in data.get('transactions', []):
            moves.append({
                'Date': t.get('date', ''),
                'Player': t.get('person', {}).get('fullName', 'Unknown'),
                'Move': t.get('typeDesc', ''),
                'Details': t.get('description', '')
            })
        moves.sort(key=lambda x: x['Date'], reverse=True)
        return moves
    except Exception:
        return []

@st.cache_data(ttl=7200)
def get_shutdown_failures(team_id, season, days_back=45):
    """Finds recent innings where the Padres scored but immediately gave the runs right back."""
    try:
        data = statsapi.get('schedule', {
            'sportId': 1, 'teamId': team_id, 'season': season,
            'gameType': 'R', 'hydrate': 'linescore'
        })
    except Exception:
        return [], Counter(), 0, 0

    cutoff = datetime.now() - timedelta(days=days_back)
    failures = []
    pitcher_failures = Counter()
    total_scored, total_allowed = 0, 0

    for date_info in data.get('dates', []):
        for game in date_info.get('games', []):
            if game.get('status', {}).get('detailedState') != 'Final' or game.get('gameType') != 'R':
                continue
            game_date_str = game.get('gameDate', '')[:10]
            try:
                game_date = datetime.strptime(game_date_str, '%Y-%m-%d')
            except Exception:
                continue
            if game_date < cutoff:
                continue

            game_pk = game['gamePk']
            away_team = game['teams']['away']['team']['name']
            home_team = game['teams']['home']['team']['name']
            is_home = game['teams']['home']['team']['id'] == team_id
            innings = game.get('linescore', {}).get('innings', [])

            for idx, inning in enumerate(innings):
                inning_num = inning.get('num', idx + 1)
                away_runs = safe_int(inning.get('away', {}).get('runs', 0))
                home_runs = safe_int(inning.get('home', {}).get('runs', 0))
                failure_half_inning, scored, allowed = None, 0, 0

                if is_home:
                    if home_runs > 0 and (idx + 1) < len(innings):
                        next_top = safe_int(innings[idx + 1].get('away', {}).get('runs', 0))
                        if next_top > 0:
                            scored, allowed = home_runs, next_top
                            failure_half_inning = ('top', inning_num + 1)
                else:
                    if away_runs > 0 and home_runs > 0:
                        scored, allowed = away_runs, home_runs
                        failure_half_inning = ('bottom', inning_num)

                if failure_half_inning:
                    half, inn_num = failure_half_inning
                    total_scored += scored
                    total_allowed += allowed
                    pitchers = []
                    try:
                        pbp = statsapi.get('game_playByPlay', {'gamePk': game_pk})
                        for play in pbp.get('allPlays', []):
                            about = play.get('about', {})
                            if about.get('inning') == inn_num and about.get('halfInning') == half:
                                p_name = play.get('matchup', {}).get('pitcher', {}).get('fullName')
                                if p_name and p_name not in pitchers:
                                    pitchers.append(p_name)
                    except Exception:
                        pass
                    for p in pitchers:
                        pitcher_failures[p] += 1
                    failures.append({
                        'Date': game_date_str,
                        'Matchup': f"{away_team} @ {home_team}",
                        'Detail': f"Scored {scored}, allowed {allowed} right back ({half.title()} {inn_num})",
                        'Pitcher(s)': ", ".join(pitchers) or "Unknown"
                    })

    failures.sort(key=lambda x: x['Date'], reverse=True)
    return failures, pitcher_failures, total_scored, total_allowed

@st.cache_data(ttl=21600)
def get_league_shutdown_benchmark(season):
    """Ranks the 30 active MLB teams by how often they immediately give back runs after scoring.
    The raw schedule endpoint also returns All-Star Games, WBC qualifiers, and affiliate games
    under gameType=R, so results are restricted to real MLB team IDs."""
    try:
        valid_ids = {t['id'] for t in statsapi.get('teams', {'sportId': 1, 'activeStatus': 'Yes'}).get('teams', [])}
        data = statsapi.get('schedule', {'sportId': 1, 'season': season, 'gameType': 'R', 'hydrate': 'linescore'})
    except Exception:
        return pd.DataFrame()

    team_names = {}
    scoring_opps = defaultdict(int)
    fails = defaultdict(int)
    games_played = defaultdict(int)

    for date_info in data.get('dates', []):
        for game in date_info.get('games', []):
            if game.get('status', {}).get('detailedState') != 'Final' or game.get('gameType') != 'R':
                continue
            away = game['teams']['away']['team']
            home = game['teams']['home']['team']
            if away['id'] not in valid_ids or home['id'] not in valid_ids:
                continue
            team_names[away['id']] = away['name']
            team_names[home['id']] = home['name']
            games_played[away['id']] += 1
            games_played[home['id']] += 1

            innings = game.get('linescore', {}).get('innings', [])
            for idx, inning in enumerate(innings):
                away_runs = safe_int(inning.get('away', {}).get('runs', 0))
                home_runs = safe_int(inning.get('home', {}).get('runs', 0))
                if away_runs > 0:
                    scoring_opps[away['id']] += 1
                    if home_runs > 0:
                        fails[away['id']] += 1
                if home_runs > 0:
                    scoring_opps[home['id']] += 1
                    if (idx + 1) < len(innings):
                        next_top = safe_int(innings[idx + 1].get('away', {}).get('runs', 0))
                        if next_top > 0:
                            fails[home['id']] += 1

    rows = []
    for t_id, name in team_names.items():
        opps = scoring_opps[t_id]
        f = fails[t_id]
        rate = (f / opps * 100) if opps > 0 else 0.0
        rows.append({'Team': name, 'GP': games_played[t_id], 'Scoring Inn': opps, 'Failures': f, 'Failure %': round(rate, 1)})

    df = pd.DataFrame(rows).sort_values(by='Failure %', ascending=False).reset_index(drop=True)
    if not df.empty:
        df.insert(0, 'Rank', range(1, len(df) + 1))
    return df

@st.cache_data(ttl=10800)
def get_bullpen_fatigue(team_id, season, days_back=30):
    """Tracks relief-pitcher workload and back-to-back usage over a recent window."""
    try:
        data = statsapi.get('schedule', {
            'sportId': 1, 'teamId': team_id, 'season': season,
            'gameType': 'R', 'hydrate': 'linescore'
        })
    except Exception:
        return pd.DataFrame()

    cutoff = datetime.now() - timedelta(days=days_back)
    pitcher_logs = defaultdict(list)

    for date_info in data.get('dates', []):
        for game in date_info.get('games', []):
            if game.get('status', {}).get('detailedState') != 'Final' or game.get('gameType') != 'R':
                continue
            game_date_str = game.get('gameDate', '')[:10]
            try:
                game_date = datetime.strptime(game_date_str, '%Y-%m-%d')
            except Exception:
                continue
            if game_date < cutoff:
                continue

            game_pk = game['gamePk']
            try:
                box = statsapi.get('game_boxscore', {'gamePk': game_pk})
                teams = box.get('teams', {})
                side = teams['home'] if teams.get('home', {}).get('team', {}).get('id') == team_id else teams['away']
                players = side.get('players', {})
                for pid in side.get('pitchers', []):
                    p = players.get(f'ID{pid}', {})
                    name = p.get('person', {}).get('fullName', 'Unknown')
                    pitches = safe_int(p.get('stats', {}).get('pitching', {}).get('numberOfPitches'))
                    if pitches > 0:
                        pitcher_logs[name].append({'date': game_date, 'pitches': pitches})
            except Exception:
                continue

    rows = []
    for pitcher, logs in pitcher_logs.items():
        avg_pitches = sum(l['pitches'] for l in logs) / len(logs) if logs else 0
        if avg_pitches > 55:
            continue  # Skip primary starters
        logs.sort(key=lambda x: x['date'])
        three_in_three, heavy_two_day = 0, 0
        for i in range(len(logs)):
            cur = logs[i]['date']
            recent_3 = [l for l in logs if 0 <= (cur - l['date']).days <= 2]
            if len(recent_3) >= 3:
                three_in_three += 1
            recent_2 = [l for l in logs if 0 <= (cur - l['date']).days <= 1]
            if len(recent_2) == 2 and sum(l['pitches'] for l in recent_2) >= 40:
                heavy_two_day += 1
        rows.append({
            'Pitcher': pitcher, 'Outings': len(logs),
            '3-in-3 Days': three_in_three, 'Heavy 2-Day Stretch': heavy_two_day
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(by=['3-in-3 Days', 'Heavy 2-Day Stretch', 'Outings'], ascending=False).reset_index(drop=True)
    return df

@st.cache_data(ttl=1800)
def get_next_series(team_id=135):
    """Groups the upcoming schedule into the next consecutive series vs. one opponent."""
    try:
        games = statsapi.schedule(team=team_id, start_date=datetime.now().strftime("%m/%d/%Y"), end_date=(datetime.now() + timedelta(days=15)).strftime("%m/%d/%Y"))
        upcoming = [g for g in games if g['status'] != 'Final']
        if not upcoming:
            return [], None, None
        anchor = upcoming[0]
        anchor_opp_id = anchor['home_id'] if anchor['away_id'] == team_id else anchor['away_id']
        anchor_opp_name = anchor['home_name'] if anchor['away_id'] == team_id else anchor['away_name']
        series = []
        for g in upcoming:
            g_opp_id = g['home_id'] if g['away_id'] == team_id else g['away_id']
            if g_opp_id != anchor_opp_id:
                break
            series.append(g)
        return series, anchor_opp_id, anchor_opp_name
    except Exception:
        return [], None, None

@st.cache_data(ttl=3600)
def get_team_snapshot(team_id, season):
    """Fetches a team's current record, streak, division rank, and run differential."""
    try:
        data = statsapi.get('standings', {'leagueId': '103,104', 'season': season})
        for rec in data.get('records', []):
            for t in rec.get('teamRecords', []):
                if t.get('team', {}).get('id') == team_id:
                    streak = t.get('streak', {})
                    return {
                        'wins': t.get('wins', 0),
                        'losses': t.get('losses', 0),
                        'games_played': t.get('gamesPlayed', t.get('wins', 0) + t.get('losses', 0)),
                        'div_rank': t.get('divisionRank', '—'),
                        'gb': t.get('divisionGamesBack', '—'),
                        'streak': streak.get('streakCode', '—'),
                        'run_diff': t.get('runDifferential', 0)
                    }
    except Exception:
        pass
    return None

@st.cache_data(ttl=3600)
def get_season_series_record(opp_id, season, team_id=135):
    """Computes this season's regular-season head-to-head record between the Padres and an opponent."""
    try:
        games = statsapi.schedule(team=team_id, opponent=opp_id, start_date=f"01/01/{season}", end_date=datetime.now().strftime("%m/%d/%Y"))
        wins, losses = 0, 0
        for g in games:
            if g['status'] != 'Final' or g.get('game_type') != 'R':
                continue
            is_home = g['home_id'] == team_id
            sd_score = safe_int(g['home_score'] if is_home else g['away_score'])
            opp_score = safe_int(g['away_score'] if is_home else g['home_score'])
            if sd_score > opp_score:
                wins += 1
            else:
                losses += 1
        return f"{wins}-{losses}"
    except Exception:
        return "—"

@st.cache_data(ttl=3600)
def get_recent_batting_splits(team_id, days_back=15):
    """Fetches recent (last N days) hitting stats for a team's active hitters, batched in one call."""
    try:
        start = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        end = datetime.now().strftime('%Y-%m-%d')
        roster = statsapi.get('team_roster', {'teamId': team_id, 'rosterType': 'active'})
        hitter_ids = [str(p['person']['id']) for p in roster.get('roster', []) if p.get('position', {}).get('abbreviation') != 'P']
        if not hitter_ids:
            return pd.DataFrame()
        data = statsapi.get('people', {
            'personIds': ",".join(hitter_ids),
            'hydrate': f'stats(group=[hitting],type=[byDateRange],startDate={start},endDate={end})'
        })
        rows, seen = [], set()
        for person in data.get('people', []):
            name = person.get('fullName', 'Unknown')
            for stat_rec in person.get('stats', []):
                for s in stat_rec.get('splits', []):
                    if name in seen:
                        continue
                    ab = safe_int(s['stat'].get('atBats'))
                    if ab >= 8:
                        seen.add(name)
                        rows.append({
                            'Player': name, 'AB': ab,
                            'AVG': s['stat'].get('avg', '.000'),
                            'OPS': safe_float(s['stat'].get('ops')),
                            'HR': safe_int(s['stat'].get('homeRuns')),
                            'RBI': safe_int(s['stat'].get('rbi'))
                        })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_recent_pitching_splits(team_id, days_back=30):
    """Fetches recent (last N days) pitching stats for a team's active pitchers, batched in one call."""
    try:
        start = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        end = datetime.now().strftime('%Y-%m-%d')
        roster = statsapi.get('team_roster', {'teamId': team_id, 'rosterType': 'active'})
        pitcher_ids = [str(p['person']['id']) for p in roster.get('roster', []) if p.get('position', {}).get('abbreviation') == 'P']
        if not pitcher_ids:
            return pd.DataFrame()
        data = statsapi.get('people', {
            'personIds': ",".join(pitcher_ids),
            'hydrate': f'stats(group=[pitching],type=[byDateRange],startDate={start},endDate={end})'
        })
        rows, seen = [], set()
        for person in data.get('people', []):
            name = person.get('fullName', 'Unknown')
            for stat_rec in person.get('stats', []):
                for s in stat_rec.get('splits', []):
                    if name in seen:
                        continue
                    ip = safe_float(s['stat'].get('inningsPitched'))
                    if ip >= 3:
                        seen.add(name)
                        rows.append({
                            'Pitcher': name,
                            'IP': s['stat'].get('inningsPitched', '0.0'),
                            'ERA': safe_float(s['stat'].get('era')),
                            'WHIP': safe_float(s['stat'].get('whip')),
                            'K': safe_int(s['stat'].get('strikeOuts')),
                            'G': safe_int(s['stat'].get('gamesPitched')),
                            'GS': safe_int(s['stat'].get('gamesStarted'))
                        })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=1800)
def get_team_news(team_name, limit=6):
    """Fetches recent news headlines for a team via Google News RSS."""
    try:
        query = f"{team_name} MLB".replace(" ", "+")
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        res = requests.get(url, headers={'User-Agent': 'PadresRadioApp/1.0'}, timeout=6)
        feed = feedparser.parse(res.content if res.status_code == 200 else url)
        items = []
        for entry in feed.entries[:limit]:
            source = entry.get('source', {}).get('title', '')
            title = entry.get('title', '')
            if source and title.endswith(f" - {source}"):
                title = title[: -(len(source) + 3)]
            items.append({
                'title': title,
                'link': entry.get('link', ''),
                'published': entry.get('published', '')[:16],
                'source': source
            })
        return items
    except Exception:
        return []

@st.cache_data(ttl=3600)
def get_last_n_record(team_id, n=10):
    """Computes a team's record over their last N completed regular-season games."""
    try:
        end = datetime.now()
        start = end - timedelta(days=45)
        games = statsapi.schedule(team=team_id, start_date=start.strftime("%m/%d/%Y"), end_date=end.strftime("%m/%d/%Y"))
        finals = [g for g in games if g['status'] == 'Final' and g.get('game_type') == 'R']
        finals.sort(key=lambda g: g['game_date'])
        last_n = finals[-n:]
        wins, losses = 0, 0
        for g in last_n:
            is_home = g['home_id'] == team_id
            t_score = safe_int(g['home_score'] if is_home else g['away_score'])
            o_score = safe_int(g['away_score'] if is_home else g['home_score'])
            if t_score > o_score:
                wins += 1
            else:
                losses += 1
        return f"{wins}-{losses}"
    except Exception:
        return "—"

@st.cache_data(ttl=3600)
def get_league_last10_records(season):
    """Computes every active MLB team's record over their last 10 completed regular-season games."""
    try:
        valid_ids = {t['id'] for t in statsapi.get('teams', {'sportId': 1, 'activeStatus': 'Yes'}).get('teams', [])}
        data = statsapi.get('schedule', {'sportId': 1, 'season': season, 'gameType': 'R', 'hydrate': 'linescore'})
    except Exception:
        return {}

    team_games = defaultdict(list)
    for date_info in data.get('dates', []):
        for game in date_info.get('games', []):
            if game.get('status', {}).get('detailedState') != 'Final' or game.get('gameType') != 'R':
                continue
            away, home = game['teams']['away'], game['teams']['home']
            away_id, home_id = away['team']['id'], home['team']['id']
            if away_id not in valid_ids or home_id not in valid_ids:
                continue
            date_str = game.get('gameDate', '')[:10]
            a_score, h_score = safe_int(away.get('score')), safe_int(home.get('score'))
            team_games[away_id].append((date_str, a_score > h_score))
            team_games[home_id].append((date_str, h_score > a_score))

    records = {}
    for t_id, games in team_games.items():
        games.sort(key=lambda x: x[0])
        last10 = games[-10:]
        w = sum(1 for _, won in last10 if won)
        l = len(last10) - w
        records[t_id] = f"{w}-{l}"
    return records

@st.cache_data(ttl=3600)
def get_qualified_hitters(team_id, season, days_back=15):
    """Splits recent hitting into qualified batters (season PA >= 3.1 x team games played)
    and a single 'riser' - a non-qualified player with 25+ recent AB and the best recent AVG."""
    try:
        snap = get_team_snapshot(team_id, season)
        team_gp = snap['games_played'] if snap else 0
        threshold = 3.1 * team_gp

        season_stats = statsapi.get('stats', {'season': season, 'stats': 'season', 'group': 'hitting', 'teamId': team_id})
        season_pa = {}
        for rec in season_stats.get('stats', []):
            for split in rec.get('splits', []):
                season_pa[split['player']['fullName']] = safe_int(split['stat'].get('plateAppearances'))

        recent_df = get_recent_batting_splits(team_id, days_back)
        if recent_df.empty:
            return pd.DataFrame(), pd.DataFrame()

        recent_df = recent_df.copy()
        recent_df['Qualified'] = recent_df['Player'].apply(lambda n: season_pa.get(n, 0) >= threshold)
        qualified = recent_df[recent_df['Qualified']].drop(columns=['Qualified'])

        non_qual = recent_df[(~recent_df['Qualified']) & (recent_df['AB'] >= 25)].drop(columns=['Qualified'])
        riser = pd.DataFrame()
        if not non_qual.empty:
            non_qual = non_qual.copy()
            non_qual['avg_num'] = non_qual['AVG'].apply(safe_float)
            riser = non_qual.sort_values(by='avg_num', ascending=False).head(1).drop(columns=['avg_num'])

        return qualified, riser
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

def get_headshot_url(player_id):
    """Direct MLB static headshot image URL for a player id."""
    return f"https://img.mlbstatic.com/mlb-photos/image/upload/w_213,d_people:generic:headshot:silo:current.png,q_auto:best,f_auto/v1/people/{player_id}/headshot/67/current"

@st.cache_data(ttl=21600)
def get_pitcher_quick_stats(pid, season):
    """Fetches a pitcher's season W-L, ERA, and saves for a quick card display."""
    try:
        pstats = statsapi.player_stat_data(pid, group="pitching", type="season")
        if pstats and pstats.get('stats'):
            s = pstats['stats'][0]['stats']
            return {'wins': s.get('wins', 0), 'losses': s.get('losses', 0), 'era': s.get('era', '—'), 'saves': s.get('saves', 0)}
    except Exception:
        pass
    return None

@st.cache_data(ttl=21600)
def get_top_highlight(game_pk):
    """Fetches the direct mp4 URL and headline for a game's top highlight clip."""
    try:
        content = statsapi.get('game_content', {'gamePk': game_pk})
        items = content.get('highlights', {}).get('highlights', {}).get('items', [])
        if not items:
            return None, None
        h = items[0]
        for p in h.get('playbacks', []):
            if p.get('name') == 'mp4Avc':
                return p.get('url'), h.get('headline', 'Game Highlight')
    except Exception:
        pass
    return None, None

# ==========================================
# 4. DASHBOARD HEADER & TAB SETUP
# ==========================================
st.markdown("<h1 style='text-align: center; color: #2F241D;'>🤎 San Diego Padres Command Center ⚾</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #755B49; font-size: 1.2em;'>Radio Prep & Real-Time Data Hub</p>", unsafe_allow_html=True)
st.markdown("---")

today = datetime.now()
padres_roster_map = get_padres_roster_map(today.year)

tab1, tab_brief, tab_injury, tab_series, tab_bullpen, tab4, tab5, tab6 = st.tabs([
    "📊 Padres Hub", "📋 Show Briefing", "🏥 Injury Report", "🔭 Series Scout",
    "🎯 Bullpen & Shutdown", "🌎 Around MLB", "🔬 Advanced Analytics", "🏆 Daily Rewind"
])

# ==========================================
# TAB: SHOW BRIEFING
# ==========================================
with tab_brief:
    st.markdown("### 📋 Show Briefing — Everything You Need Before You're On Air")
    st.caption(f"Generated {datetime.now().strftime('%A, %B %d @ %I:%M %p')}")
    st.markdown("---")

    y_label, y_delta, y_color, nl_wc_df, p_wc_row = get_padres_wc_hub_data()
    il_list = get_injury_report(135)
    recent_moves = get_recent_transactions(135, 10)
    bp_df = get_bullpen_fatigue(135, today.year, 30)
    sd_failures, sd_pitcher_counts, sd_scored, sd_allowed = get_shutdown_failures(135, today.year, 45)

    next_game, last_game = None, None
    try:
        window = statsapi.schedule(team=135, start_date=(today - timedelta(days=10)).strftime("%m/%d/%Y"), end_date=(today + timedelta(days=10)).strftime("%m/%d/%Y"))
        finals = [g for g in window if g['status'] == 'Final']
        if finals: last_game = finals[-1]
        upcoming = [g for g in window if g['status'] != 'Final']
        if upcoming: next_game = upcoming[0]
    except Exception:
        pass

    ctx_col1, ctx_col2, ctx_col3 = st.columns(3)
    with ctx_col1:
        if next_game:
            badge = "🚨 TODAY" if next_game['game_date'] == today.strftime("%Y-%m-%d") else next_game['game_date']
            ap, hp = next_game.get('away_probable_pitcher') or 'TBD', next_game.get('home_probable_pitcher') or 'TBD'
            sd_p, opp_p = (ap, hp) if 'Padres' in next_game['away_name'] else (hp, ap)
            st.metric("Next Game", f"{next_game['away_name'].split()[-1]} @ {next_game['home_name'].split()[-1]}", delta=badge)
            st.caption(f"🤎 SD: {sd_p}  |  🧢 OPP: {opp_p}")
        else:
            st.metric("Next Game", "No upcoming game found")
    with ctx_col2:
        st.metric("Yesterday's Result", y_label, delta=y_delta, delta_color=y_color)
    with ctx_col3:
        if p_wc_row:
            st.metric("Wild Card Position", p_wc_row.get('Rank', 'NL West'), delta=f"GB: {p_wc_row.get('GB', '—')}")
        else:
            st.metric("Wild Card Position", "NL West Contender")

    st.markdown("---")
    st.markdown("### 🔥 Tonight's Top Talking Points")

    points = []
    if last_game:
        points.extend(get_game_topics(last_game))
    if il_list:
        names = ", ".join(p['Player'] for p in il_list[:3])
        extra = " and others" if len(il_list) > 3 else ""
        points.append(f"🏥 **Injury Watch:** {names}{extra} — {len(il_list)} total Padres currently on the IL.")
    if recent_moves:
        m = recent_moves[0]
        points.append(f"📋 **Latest Roster Move:** {m['Details']} ({m['Date']})")
    if not bp_df.empty and bp_df.iloc[0]['Outings'] > 0:
        top_reliever = bp_df.iloc[0]
        points.append(f"😮‍💨 **Bullpen Watch:** {top_reliever['Pitcher']} has been the most-used arm over the last 30 days ({int(top_reliever['Outings'])} outings, {int(top_reliever['3-in-3 Days'])} stretch(es) of 3-in-3 days).")
    if sd_failures:
        diff = sd_scored - sd_allowed
        points.append(f"📉 **Shutdown Failures:** The Padres have given runs right back {len(sd_failures)} time(s) in the last 45 days (net {diff:+d} runs in those innings). Most recent: {sd_failures[0]['Matchup']} on {sd_failures[0]['Date']}.")
    points.append(f"🎙️ **Trivia Nugget:** {random.choice(TRIVIA_BANK)['q']}")

    if points:
        for pt in points[:8]:
            st.markdown(f"- {pt}")
    else:
        st.info("Building talking points... check back once game data loads.")

    st.markdown("---")
    snap1, snap2 = st.columns(2)
    with snap1:
        st.markdown("#### 🏥 Injury List Snapshot")
        if il_list:
            st.dataframe(pd.DataFrame(il_list), width='stretch', hide_index=True)
        else:
            st.success("No Padres players currently on the IL. 🎉")
    with snap2:
        st.markdown("#### 😮‍💨 Bullpen Workload (Last 30 Days)")
        if not bp_df.empty:
            st.dataframe(bp_df.head(6), width='stretch', hide_index=True)
        else:
            st.caption("Bullpen workload data updating...")

# ==========================================
# TAB 1: PADRES HUB
# ==========================================
with tab1:
    st.markdown("### 🎫 Padres Wild Card Radar & Live Performance Indicator")
    y_label, y_delta, y_color, nl_wc_df, p_wc_row = get_padres_wc_hub_data()
    
    with st.container(border=True):
        sc_col1, sc_col2, sc_col3 = st.columns([1, 1, 2])
        
        with sc_col1:
            if p_wc_row:
                st.metric(
                    label="Padres Wild Card Rank",
                    value=p_wc_row.get('Rank', 'NL West'),
                    delta=f"GB: {p_wc_row.get('GB', '—')}"
                )
            else:
                st.metric(label="Padres WC Rank", value="NL West Contender")
                
        with sc_col2:
            st.metric(
                label="Yesterday's Result",
                value=y_label,
                delta=y_delta,
                delta_color=y_color
            )
            
        with sc_col3:
            st.markdown("**NL Wild Card Race Snapshot**")
            if not nl_wc_df.empty:
                st.dataframe(nl_wc_df.head(6), width='stretch', hide_index=True)
            else:
                st.caption("NL Wild Card standings updating...")

    st.markdown("---")
    st.markdown("### 🕒 Recent Form: The Last 3 Games")
    ten_days_ago = today - timedelta(days=10)
    
    try:
        games = statsapi.schedule(team=135, start_date=ten_days_ago.strftime("%m/%d/%Y"), end_date=today.strftime("%m/%d/%Y"))
        completed_games = [g for g in games if g['status'] == 'Final'][-3:]
        completed_games.reverse()

        if completed_games:
            cols = st.columns(3)
            for idx, game in enumerate(completed_games):
                with cols[idx]:
                    with st.container(border=True):
                        st.caption(f"🗓️ {game['game_date']} · FINAL")

                        away_snap = get_team_snapshot(game['away_id'], today.year)
                        home_snap = get_team_snapshot(game['home_id'], today.year)
                        away_rec = f" ({away_snap['wins']}-{away_snap['losses']})" if away_snap else ""
                        home_rec = f" ({home_snap['wins']}-{home_snap['losses']})" if home_snap else ""

                        st.markdown(f"""
<div style="display:flex; justify-content:space-between; align-items:baseline; gap:8px;">
  <span><b>{game['away_name']}</b>{away_rec}</span>
  <span style="font-family:monospace; font-size:1.15em; font-weight:bold; flex-shrink:0;">{game['away_score']}</span>
</div>
<div style="display:flex; justify-content:space-between; align-items:baseline; gap:8px;">
  <span><b>{game['home_name']}</b>{home_rec}</span>
  <span style="font-family:monospace; font-size:1.15em; font-weight:bold; flex-shrink:0;">{game['home_score']}</span>
</div>
""", unsafe_allow_html=True)

                        try:
                            game_data = statsapi.get('game', {'gamePk': game['game_id']})
                        except Exception:
                            game_data = {}
                        decisions = game_data.get('liveData', {}).get('decisions', {})
                        winner, loser, save = decisions.get('winner'), decisions.get('loser'), decisions.get('save')

                        dp_entries = [('W', winner), ('L', loser)] + ([('SV', save)] if save else [])
                        dp_cols = st.columns(len(dp_entries))
                        for dp_idx, (label, person) in enumerate(dp_entries):
                            if not person:
                                continue
                            with dp_cols[dp_idx]:
                                qs = get_pitcher_quick_stats(person['id'], today.year)
                                st.image(get_headshot_url(person['id']), width=48)
                                st.caption(f"**{label}: {person['fullName']}**")
                                if qs:
                                    if label == 'SV':
                                        st.caption(f"{qs['saves']} SV")
                                    else:
                                        st.caption(f"{qs['wins']}-{qs['losses']}, {qs['era']} ERA")

                        with st.expander("📊 Box Score, Standout Performers & Highlight"):
                            w_p = game.get('winning_pitcher', 'None')
                            sv_p = game.get('save_pitcher', '')
                            is_padres_home = "Padres" in game['home_name']
                            padres_score = game['home_score'] if is_padres_home else game['away_score']
                            padres_batters_key = 'homeBatters' if is_padres_home else 'awayBatters'
                            padres_won = (is_padres_home and game['home_score'] > game['away_score']) or (not is_padres_home and game['away_score'] > game['home_score'])

                            padres_performers = []
                            if padres_won:
                                if w_p and w_p != 'None': padres_performers.append(f"⚾ **{w_p}** (WIN)")
                                if sv_p and sv_p not in ['None', '']: padres_performers.append(f"🔒 **{sv_p}** (SAVE)")

                            try:
                                box = statsapi.boxscore_data(game['game_id'])
                                hr_hitters, rbi_hitters = [], []
                                for b in box.get(padres_batters_key, []):
                                    if isinstance(b, dict) and 'name' in b and b['name'].lower() != 'totals':
                                        name = b['name']
                                        hr, rbi = safe_int(b.get('hr', b.get('homeRuns'))), safe_int(b.get('rbi', b.get('runsBattedIn')))
                                        h, ab = safe_int(b.get('h', b.get('hits'))), safe_int(b.get('ab', b.get('atBats')))
                                        if hr > 0: hr_hitters.append(f"💣 **{name}**: {hr} HR, {rbi} RBI ({h}-{ab})")
                                        elif rbi > 0: rbi_hitters.append(f"🏏 **{name}**: {rbi} RBI ({h}-{ab})")

                                if hr_hitters: padres_performers.extend(hr_hitters)
                                elif padres_score == 1 and rbi_hitters: padres_performers.extend(rbi_hitters)
                                elif padres_score > 1 and rbi_hitters: padres_performers.extend(rbi_hitters[:2])
                            except Exception:
                                pass

                            top_3 = padres_performers[:3]
                            if top_3:
                                st.markdown("**🌟 Standout Performers:**")
                                for perf in top_3: st.markdown(f"- {perf}")

                            st.markdown("---")
                            try:
                                linescore = game_data.get('liveData', {}).get('linescore', {})
                                innings = linescore.get('innings', [])
                                headers = ['Team'] + [str(i + 1) for i in range(len(innings))] + ['R', 'H', 'E']
                                away_row, home_row = [game['away_name']], [game['home_name']]

                                for inn in innings:
                                    away_row.append(inn.get('away', {}).get('runs', 0))
                                    hruns = inn.get('home', {}).get('runs', '')
                                    home_row.append(hruns if hruns != '' else '-')

                                teams_t = linescore.get('teams', {})
                                away_row.extend([teams_t.get('away', {}).get('runs', 0), teams_t.get('away', {}).get('hits', 0), teams_t.get('away', {}).get('errors', 0)])
                                home_row.extend([teams_t.get('home', {}).get('runs', 0), teams_t.get('home', {}).get('hits', 0), teams_t.get('home', {}).get('errors', 0)])
                                st.dataframe(pd.DataFrame([away_row, home_row], columns=headers), width='stretch', hide_index=True)
                            except Exception:
                                st.caption("Inning-by-inning data unavailable.")

                            st.markdown("---")
                            st.markdown("📺 **Top Highlight**")
                            video_url, headline = get_top_highlight(game['game_id'])
                            if video_url:
                                st.video(video_url)
                                st.caption(headline)
                            else:
                                search_term = f"{game['away_name']} vs {game['home_name']} {game['game_date']} highlights".replace(" ", "+")
                                st.markdown(f"**[Watch on YouTube](https://www.youtube.com/results?search_query={search_term})**")
        else:
            st.info("No completed games found recently.")
    except Exception as e:
        st.error(f"Couldn't fetch past games: {e}")

    st.markdown("---")
    st.markdown("### 🗓️ Next Up: Upcoming 3 Matchups")
    try:
        future_games = statsapi.schedule(team=135, start_date=today.strftime("%m/%d/%Y"), end_date=(today + timedelta(days=15)).strftime("%m/%d/%Y"))
        next_3 = [g for g in future_games if g['status'] != 'Final'][:3]
        if next_3:
            cols = st.columns(3)
            for idx, game in enumerate(next_3):
                with cols[idx]:
                    with st.container(border=True):
                        away, home = game['away_name'], game['home_name']
                        ap, hp = game.get('away_probable_pitcher', '') or 'TBD', game.get('home_probable_pitcher', '') or 'TBD'
                        badge = "🚨 (TODAY)" if game['game_date'] == today.strftime("%Y-%m-%d") else ""
                        st.markdown(f"#### {away} @ {home} {badge}")
                        st.caption(f"📅 {game['game_date']} | Status: `{game['status']}`")
                        
                        sd_p, opp_p = (ap, hp) if 'Padres' in away else (hp, ap)
                        st.markdown(f"**🤎 SD:** `{sd_p}` | **🧢 OPP:** `{opp_p}`")
                        
                        if opp_p != 'TBD':
                            with st.expander("🔍 Scout Starter & Batter Matchups"):
                                try:
                                    opp_lookup = statsapi.lookup_player(opp_p)
                                    if not opp_lookup:
                                        opp_lookup = statsapi.lookup_player(clean_player_name(opp_p))
                                        
                                    if opp_lookup:
                                        opp_id = opp_lookup[0]['id']
                                        stats = statsapi.player_stat_data(opp_id, group="pitching", type="season")
                                        if stats and 'stats' in stats and len(stats['stats']) > 0:
                                            ps = stats['stats'][0]['stats']
                                            sc1, sc2 = st.columns(2)
                                            sc1.metric("ERA", ps.get('era', 'N/A'))
                                            sc2.metric("WHIP", ps.get('whip', 'N/A'))
                                            
                                        st.markdown("🎯 **Career Matchups vs. Padres Hitting Core**")
                                        if padres_roster_map:
                                            bvp_data = get_bvp_matchups(opp_id, list(padres_roster_map.keys()), padres_roster_map)
                                            if bvp_data:
                                                bvp_df = pd.DataFrame(bvp_data).sort_values(by='AB', ascending=False)
                                                
                                                bvp_df['Hitter'] = bvp_df.apply(
                                                    lambda r: f"🟢 {r['Hitter']} (.300+)" if safe_float(r['AVG']) >= 0.300 else r['Hitter'], 
                                                    axis=1
                                                )
                                                
                                                def highlight_300(row):
                                                    try:
                                                        if safe_float(row['AVG']) >= 0.300:
                                                            return ['background-color: rgba(40, 167, 69, 0.25); color: #2ecc71; font-weight: bold'] * len(row)
                                                    except Exception:
                                                        pass
                                                    return [''] * len(row)

                                                styled_bvp = bvp_df.style.apply(highlight_300, axis=1)
                                                st.dataframe(styled_bvp, width='stretch', hide_index=True)
                                            else:
                                                st.caption("No historical matchups.")
                                        else:
                                            st.caption("Padres roster updating...")
                                    else:
                                        st.caption("Pitcher data not found.")
                                except Exception as e:
                                    st.caption("Scouting data syncing...")
        else:
            st.info("No upcoming games found.")
    except Exception as e:
        st.error(f"Couldn't fetch upcoming schedule: {e}")

    st.markdown("---")
    st.markdown("### 🤖 AI & Predictive Season Projections")
    ai_proj = calculate_ai_projections(today.year)
    if ai_proj:
        with st.container(border=True):
            p_col1, p_col2 = st.columns([1, 2.2])
            with p_col1:
                st.markdown("#### 🏆 Projected Final Record")
                st.metric("Projected Wins", f"{ai_proj['team_wins']} - {ai_proj['team_losses']}", delta=f"{ai_proj['team_wins'] - 81} Wins vs .500")
                st.caption(f"Current Record: {ai_proj['current_wins']}-{ai_proj['current_losses']}")
            with p_col2:
                st.markdown("#### ⚡ Star Player 162-Game Projections")
                h_tab, p_tab = st.tabs(["🏏 Big Three Hitters", "🔥 Reliever Focus (Mason Miller)"])
                with h_tab: st.dataframe(pd.DataFrame(ai_proj['hitters']), width='stretch', hide_index=True)
                with p_tab: st.dataframe(pd.DataFrame(ai_proj['pitchers']), width='stretch', hide_index=True)

    st.markdown("---")
    st.markdown("### 📊 Sortable Player Hitting Stats")
    try:
        if padres_roster_map:
            p_list = []
            raw_stats = statsapi.get('stats', {'season': today.year, 'stats': 'season', 'group': 'hitting', 'teamId': 135})
            for rec in raw_stats.get('stats', []):
                for split in rec.get('splits', []):
                    st_data = split['stat']
                    p_list.append({
                        "Player": split['player']['fullName'],
                        "GP": st_data.get('gamesPlayed', 0),
                        "AVG": float(st_data.get('avg', '.000')), 
                        "HR": st_data.get('homeRuns', 0),
                        "RBI": st_data.get('runsBattedIn', 0),
                        "OBP": float(st_data.get('obp', '.000')),
                        "OPS": float(st_data.get('ops', '.000')),
                        "SB": st_data.get('stolenBases', 0)
                    })
            st.dataframe(pd.DataFrame(p_list), width='stretch', hide_index=True)
    except Exception as e:
        st.error(f"Couldn't load stats table: {e}")

# ==========================================
# TAB: INJURY REPORT
# ==========================================
with tab_injury:
    st.markdown("### 🏥 Padres Injury Report & Roster Moves")
    st.markdown("---")

    il_list = get_injury_report(135)
    ic1, ic2 = st.columns([1.4, 1])

    with ic1:
        st.markdown("#### 🩹 Currently on the Injured List")
        if il_list:
            st.dataframe(pd.DataFrame(il_list), width='stretch', hide_index=True)
            st.caption(f"{len(il_list)} player(s) on the IL.")
        else:
            st.success("No Padres players currently on the Injured List.")

    with ic2:
        st.markdown("#### 📋 Recent Roster Transactions (Last 14 Days)")
        moves = get_recent_transactions(135, 14)
        if moves:
            for m in moves[:12]:
                with st.container(border=True):
                    st.markdown(f"**{m['Date']}** — {m['Move']}")
                    st.caption(m['Details'])
        else:
            st.caption("No recent transactions found.")

# ==========================================
# TAB: SERIES SCOUT
# ==========================================
with tab_series:
    st.markdown("### 🔭 Series Scout — Next Opponent Deep Dive")
    st.markdown("---")

    series_games, opp_id, opp_name = get_next_series()

    if not opp_id:
        st.info("No upcoming series found.")
    else:
        snap = get_team_snapshot(opp_id, today.year)
        series_record = get_season_series_record(opp_id, today.year)
        last10 = get_last_n_record(opp_id, 10)

        hc1, hc2, hc3, hc4, hc5 = st.columns(5)
        with hc1:
            dates = ", ".join(g['game_date'][5:] for g in series_games)
            venue = "Home" if series_games[0]['home_id'] == 135 else "Away"
            st.metric("Next Series", opp_name)
            st.caption(f"{len(series_games)} game(s) ({venue}): {dates}")
        with hc2:
            if snap:
                st.metric(f"{opp_name} Record", f"{snap['wins']}-{snap['losses']}", delta=f"Streak: {snap['streak']}")
            else:
                st.metric(f"{opp_name} Record", "—")
        with hc3:
            st.metric("Last 10", last10)
        with hc4:
            if snap:
                st.metric("Division Rank", f"#{snap['div_rank']}", delta=f"GB: {snap['gb']}")
            else:
                st.metric("Division Rank", "—")
        with hc5:
            st.metric("Season Series vs SD", series_record)

        st.markdown("---")
        st.markdown(f"### 🌡️ Who's Hot & Who's Cold: {opp_name} Hitters (Last 15 Days)")
        st.caption("Limited to qualified batters (season PA ≥ 3.1 × team games played), plus a 🆕 riser: a non-qualified player with 25+ recent AB leading the team in AVG.")
        qualified_df, riser_df = get_qualified_hitters(opp_id, today.year, 15)
        h1, h2 = st.columns(2)
        with h1:
            st.markdown("#### 🔥 Hot Hitters (Most HR)")
            if not qualified_df.empty:
                hot_hitters = qualified_df.sort_values(by='HR', ascending=False).head(5).copy()
                if not riser_df.empty:
                    riser_row = riser_df.copy()
                    riser_row['Player'] = riser_row['Player'] + ' 🆕'
                    hot_hitters = pd.concat([hot_hitters, riser_row], ignore_index=True)
                st.dataframe(hot_hitters, width='stretch', hide_index=True)
            else:
                st.caption("Recent hitting data updating...")
        with h2:
            st.markdown("#### 🥶 Cold Hitters (Lowest AVG)")
            if not qualified_df.empty:
                cold_hitters = qualified_df.copy()
                cold_hitters['avg_num'] = cold_hitters['AVG'].apply(safe_float)
                cold_hitters = cold_hitters.sort_values(by='avg_num', ascending=True).head(5).drop(columns=['avg_num'])
                st.dataframe(cold_hitters, width='stretch', hide_index=True)
            else:
                st.caption("Recent hitting data updating...")

        st.markdown("---")
        st.markdown(f"### ⚾ Arms: Hot & Cold (Last 30 Days)")
        pitch_df = get_recent_pitching_splits(opp_id, 30)
        if not pitch_df.empty:
            starters_df = pitch_df[pitch_df['GS'] > 0].drop(columns=['GS', 'G'])
            relievers_df = pitch_df[(pitch_df['GS'] == 0) & (pitch_df['G'] >= 3)].drop(columns=['GS'])
        else:
            starters_df, relievers_df = pd.DataFrame(), pd.DataFrame()

        st.markdown("#### 🎯 Starters")
        st.caption("Hot = ranked by strikeouts if K > IP, otherwise by innings pitched. Cold = highest ERA.")
        sp1, sp2 = st.columns(2)
        with sp1:
            st.markdown("🔥 **Hot Starters**")
            if not starters_df.empty:
                hot_starters = starters_df.copy()
                hot_starters['sort_key'] = hot_starters.apply(lambda r: r['K'] if r['K'] > safe_float(r['IP']) else safe_float(r['IP']), axis=1)
                hot_starters = hot_starters.sort_values(by='sort_key', ascending=False).head(5).drop(columns=['sort_key'])
                st.dataframe(hot_starters, width='stretch', hide_index=True)
            else:
                st.caption("No qualifying starters in this window.")
        with sp2:
            st.markdown("🥶 **Cold Starters**")
            if not starters_df.empty:
                st.dataframe(starters_df.sort_values(by='ERA', ascending=False).head(5), width='stretch', hide_index=True)
            else:
                st.caption("No qualifying starters in this window.")

        st.markdown("#### 💪 Relievers")
        st.caption("Ranked by ERA, minimum 3 appearances in the window.")
        rp1, rp2 = st.columns(2)
        with rp1:
            st.markdown("🔥 **Hot Relievers (Lowest ERA)**")
            if not relievers_df.empty:
                st.dataframe(relievers_df.sort_values(by='ERA', ascending=True).head(5), width='stretch', hide_index=True)
            else:
                st.caption("No qualifying relievers in this window.")
        with rp2:
            st.markdown("🥶 **Cold Relievers (Highest ERA)**")
            if not relievers_df.empty:
                st.dataframe(relievers_df.sort_values(by='ERA', ascending=False).head(5), width='stretch', hide_index=True)
            else:
                st.caption("No qualifying relievers in this window.")

        st.markdown("---")
        st.markdown(f"### 🏥 {opp_name} Injury Report")
        opp_il = get_injury_report(opp_id)
        if opp_il:
            st.dataframe(pd.DataFrame(opp_il), width='stretch', hide_index=True)
        else:
            st.success(f"No {opp_name} players currently on the IL.")

        st.markdown("---")
        st.markdown(f"### 📰 Latest {opp_name} News")
        news = get_team_news(opp_name)
        if news:
            n_cols = st.columns(2)
            for idx, n in enumerate(news):
                with n_cols[idx % 2]:
                    with st.container(border=True):
                        st.markdown(f"**[{n['title']}]({n['link']})**")
                        st.caption(f"{n['source']} · {n['published']}" if n['source'] else n['published'])
        else:
            st.caption("News feed unavailable.")

# ==========================================
# TAB: BULLPEN & SHUTDOWN REPORT
# ==========================================
with tab_bullpen:
    st.markdown("### 🎯 Bullpen Fatigue & Shutdown Failure Report")
    st.caption("Innings where the Padres score, then immediately give it right back — plus who's been overworked in relief.")
    st.markdown("---")

    bp_df = get_bullpen_fatigue(135, today.year, 30)
    sd_failures, sd_pitcher_counts, sd_scored, sd_allowed = get_shutdown_failures(135, today.year, 45)

    b1, b2 = st.columns(2)
    with b1:
        st.markdown("#### 😮‍💨 Reliever Workload (Last 30 Days)")
        if not bp_df.empty:
            st.dataframe(bp_df, width='stretch', hide_index=True)
            st.caption("3-in-3 Days = appeared in 3 straight games. Heavy 2-Day Stretch = 40+ pitches across back-to-back outings.")
        else:
            st.caption("Bullpen workload data updating...")

    with b2:
        st.markdown("#### 📉 Shutdown Failure Pitcher Tally (Last 45 Days)")
        if sd_pitcher_counts:
            tally_df = pd.DataFrame(sd_pitcher_counts.most_common(), columns=['Pitcher', 'Failures'])
            st.dataframe(tally_df, width='stretch', hide_index=True)
        else:
            st.caption("No shutdown failures logged in this window.")

    st.markdown("---")
    diff = sd_scored - sd_allowed
    m1, m2, m3 = st.columns(3)
    m1.metric("Shutdown Failures (45d)", len(sd_failures))
    m2.metric("Runs Scored in Those Innings", sd_scored)
    m3.metric("Runs Allowed Right Back", sd_allowed, delta=f"{diff:+d} net")

    if sd_failures:
        st.markdown("#### 🗒️ Failure Log")
        st.dataframe(pd.DataFrame(sd_failures), width='stretch', hide_index=True)

    st.markdown("---")
    st.markdown("#### 🏆 League-Wide Shutdown Failure Benchmark")
    st.caption("How often does each team immediately give back the lead after scoring? Lower is better.")
    league_df = get_league_shutdown_benchmark(today.year)
    if not league_df.empty:
        padres_rank_row = league_df[league_df['Team'].str.contains('Padres', case=False)]
        if not padres_rank_row.empty:
            st.info(f"🤎 Padres rank **#{int(padres_rank_row.iloc[0]['Rank'])} of {len(league_df)}** in shutdown failure rate ({padres_rank_row.iloc[0]['Failure %']}%).")
        st.dataframe(league_df, width='stretch', hide_index=True)
    else:
        st.caption("League benchmark data updating...")

# ==========================================
# TAB 4: AROUND MLB (DEDICATED MLB TRADE RUMORS)
# ==========================================
with tab4:
    st.markdown("### 🌎 Major League Baseball Command Center")
    st.markdown("---")

    st.markdown("### 🎫 Live Postseason Wild Card Race")
    wc_col1, wc_col2 = st.columns(2)

    with wc_col1:
        st.markdown("#### 🟦 National League Wild Card")
        nl_wc_df = get_wildcard_standings(104)
        if not nl_wc_df.empty:
            st.dataframe(nl_wc_df, width='stretch', hide_index=True)
        else:
            st.caption("NL Wild Card standings updating...")

    with wc_col2:
        st.markdown("#### 🟥 American League Wild Card")
        al_wc_df = get_wildcard_standings(103)
        if not al_wc_df.empty:
            st.dataframe(al_wc_df, width='stretch', hide_index=True)
        else:
            st.caption("AL Wild Card standings updating...")

    st.markdown("---")
    st.markdown("### 🏆 Full MLB Division Matrix")
    last10_map = get_league_last10_records(today.year)

    def with_last10(df):
        if df.empty or '_id' not in df.columns:
            return df
        out = df.copy()
        out['L10'] = out['_id'].apply(lambda i: last10_map.get(i, '—'))
        return out.drop(columns=['_id'])

    st.markdown("#### 🟦 National League Divisions")
    nl_c1, nl_c2, nl_c3 = st.columns(3)
    nl_divs = get_full_standings(104)
    for d_name, df in nl_divs.items():
        col = nl_c1 if "East" in d_name else (nl_c2 if "Central" in d_name else nl_c3)
        with col:
            st.markdown(f"**{d_name}**")
            st.dataframe(with_last10(df), width='stretch', hide_index=True)

    st.markdown("#### 🟥 American League Divisions")
    al_c1, al_c2, al_c3 = st.columns(3)
    al_divs = get_full_standings(103)
    for d_name, df in al_divs.items():
        col = al_c1 if "East" in d_name else (al_c2 if "Central" in d_name else al_c3)
        with col:
            st.markdown(f"**{d_name}**")
            st.dataframe(with_last10(df), width='stretch', hide_index=True)

    st.markdown("---")
    st.markdown(f"### 🌟 MLB Stat Leaders ({today.year})")
    scope = st.radio("Scope", ["MLB", "NL", "AL"], horizontal=True, key="stat_leader_scope")
    league_id = {"NL": 104, "AL": 103, "MLB": None}[scope]
    with st.container(border=True):
        lt1, lt2, lt3, lt4 = st.tabs(["💣 Home Runs", "📈 OPS", "⚾ ERA", "🔥 Strikeouts"])

        with lt1:
            hr_df = get_clean_leaders('homeRuns', 'hitting', today.year, league_id)
            if not hr_df.empty:
                st.dataframe(hr_df, width='stretch', hide_index=True)
            else:
                st.caption("Home Run leaders updating...")

        with lt2:
            ops_df = get_clean_leaders('onBasePlusSlugging', 'hitting', today.year, league_id)
            if not ops_df.empty:
                st.dataframe(ops_df, width='stretch', hide_index=True)
            else:
                st.caption("OPS leaders updating...")

        with lt3:
            era_df = get_clean_leaders('earnedRunAverage', 'pitching', today.year, league_id)
            if not era_df.empty:
                st.dataframe(era_df, width='stretch', hide_index=True)
            else:
                st.caption("ERA leaders updating...")

        with lt4:
            so_df = get_clean_leaders('strikeouts', 'pitching', today.year, league_id)
            if not so_df.empty:
                st.dataframe(so_df, width='stretch', hide_index=True)
            else:
                st.caption("Strikeout leaders updating...")

    st.markdown("---")
    st.markdown("### 🔥 MLB Trade Rumors & News")
    with st.container(border=True):
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) PadresRadioApp/1.0'}
            res = requests.get("https://www.mlbtraderumors.com/feed", headers=headers, timeout=5)
            feed = feedparser.parse(res.content if res.status_code == 200 else "https://www.mlbtraderumors.com/feed")

            if feed.entries:
                news_cols = st.columns(3)
                for idx, entry in enumerate(feed.entries[:9]):
                    with news_cols[idx % 3]:
                        st.markdown(f"**[{entry.title}]({entry.link})**")
                        if hasattr(entry, 'published') and entry.published:
                            st.caption(f"⏱️ {entry.published[:16]}")
                        if hasattr(entry, 'summary') and entry.summary:
                            clean_summary = entry.summary.replace('<p>', '').replace('</p>', '').replace('<br>', '').replace('<br/>', '')
                            if len(clean_summary) > 130:
                                clean_summary = clean_summary[:130] + "..."
                            st.caption(clean_summary)
                        st.markdown("---")
            else:
                st.caption("No recent rumors found.")
        except Exception:
            st.caption("MLB Trade Rumors feed updating...")

# ==========================================
# TAB 5: ADVANCED ANALYTICS
# ==========================================
with tab5:
    st.markdown("### 🔬 Advanced Sabermetrics & Statcast Data")
    st.markdown("---")
    
    @st.cache_data(ttl=43200)
    def load_fg_hitting(yr):
        try: return pyb.batting_stats(yr, qual=20)
        except Exception: return pyb.batting_stats_bref(yr)

    @st.cache_data(ttl=43200)
    def load_fg_pitching(yr):
        try: return pyb.pitching_stats(yr, qual=20)
        except Exception: return pyb.pitching_stats_bref(yr)

    def isolate_padres(df):
        if df is None or df.empty: return pd.DataFrame()
        t_col = next((c for c in df.columns if c.lower() in ['team', 'tm', 'teamname']), None)
        if t_col:
            clean = df[t_col].astype(str).str.strip().str.upper()
            return df[clean.isin(['SDP', 'SD', 'SAN DIEGO', 'PADRES', 'SAN DIEGO PADRES', 'SDG'])]
        return df

    fg_h, fg_p = load_fg_hitting(today.year), load_fg_pitching(today.year)
    ac1, ac2 = st.columns(2)
    
    with ac1:
        st.markdown("#### 🏏 Hitting Value (Leaderboard)")
        p_h = isolate_padres(fg_h)
        if not p_h.empty:
            desired_h_cols = ['Name', 'G', 'PA', 'HR', 'WAR', 'BA', 'OBP', 'OPS', 'wRC+']
            cols = [c for c in desired_h_cols if c in p_h.columns]
            if cols:
                sort_col = 'WAR' if 'WAR' in cols else cols[0]
                st.dataframe(p_h[cols].sort_values(by=sort_col, ascending=False), width='stretch', hide_index=True)
            else:
                st.dataframe(p_h, width='stretch', hide_index=True)
        else: 
            st.caption("Padres hitting data updating...")
        
    with ac2:
        st.markdown("#### ⚾ Pitching Value (Leaderboard)")
        p_p = isolate_padres(fg_p)
        if not p_p.empty:
            desired_p_cols = ['Name', 'IP', 'ERA', 'FIP', 'WHIP', 'K/9', 'SO', 'WAR']
            cols = [c for c in desired_p_cols if c in p_p.columns]
            if cols:
                sort_col = 'WAR' if 'WAR' in cols else cols[0]
                st.dataframe(p_p[cols].sort_values(by=sort_col, ascending=False), width='stretch', hide_index=True)
            else:
                st.dataframe(p_p, width='stretch', hide_index=True)
        else: 
            st.caption("Padres pitching data updating...")

# ==========================================
# TAB 6: DAILY REWIND
# ==========================================
with tab6:
    yesterday = today - timedelta(days=1)
    st.markdown(f"### 🏆 Daily Rewind: {yesterday.strftime('%A, %B %d')}")
    st.markdown("---")
    
    @st.cache_data(ttl=43200)
    def get_yesterdays_stars(date_str):
        hitters, pitchers = [], []
        try:
            for g in statsapi.schedule(date=date_str):
                if g.get('status') == 'Final':
                    box = statsapi.boxscore_data(g['game_id'])
                    for tk, tn in [('awayBatters', g['away_name']), ('homeBatters', g['home_name'])]:
                        for b in box.get(tk, []):
                            if isinstance(b, dict) and b.get('name', '').lower() != 'totals':
                                h, rbi, hr = safe_int(b.get('h')), safe_int(b.get('rbi')), safe_int(b.get('hr'))
                                if h >= 3 or rbi >= 3 or hr >= 1:
                                    hitters.append({'Player': b['name'], 'Team': tn, 'HR': hr, 'RBI': rbi})
                    for tk, tn in [('awayPitchers', g['away_name']), ('homePitchers', g['home_name'])]:
                        for p in box.get(tk, []):
                            if isinstance(p, dict) and p.get('name', '').lower() != 'totals':
                                k, er = safe_int(p.get('k')), safe_int(p.get('er'))
                                if k >= 7 or (safe_float(p.get('ip')) >= 6.0 and er <= 1):
                                    pitchers.append({'Player': p['name'], 'Team': tn, 'IP': str(p.get('ip')), 'K': k})
        except Exception: pass
        return hitters, pitchers

    top_h, top_p = get_yesterdays_stars(yesterday.strftime("%m/%d/%Y"))
    rc1, rc2 = st.columns(2)
    
    with rc1:
        st.markdown("#### 🏏 Top Hitters (Yesterday)")
        if top_h:
            st.dataframe(pd.DataFrame(top_h).head(10), width='stretch', hide_index=True)
        else:
            st.caption("No standout hitters.")
            
    with rc2:
        st.markdown("#### ⚾ Top Pitchers (Yesterday)")
        if top_p:
            st.dataframe(pd.DataFrame(top_p).head(10), width='stretch', hide_index=True)
        else:
            st.caption("No standout pitchers.")