import urllib.request
import json
import ssl
from collections import defaultdict

def analyze_league_shutdowns(season=2026):
    # Fetch schedule with linescores for the entire league in ONE request
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&season={season}&gameType=R&hydrate=linescore"
    
    print(f"Fetching complete {season} MLB schedule and linescores...")
    try:
        context = ssl.create_default_context()
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=context, timeout=20) as response:
            data = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"❌ Connection or API error: {e}")
        return

    team_names = {}
    scoring_opportunities = defaultdict(int)  # Half-innings where team scored >= 1 run
    shutdown_failures = defaultdict(int)      # Innings where team gave runs right back
    runs_scored_in_failures = defaultdict(int)
    runs_allowed_in_failures = defaultdict(int)
    games_played = defaultdict(int)

    games_count = 0

    for date_info in data.get('dates', []):
        for game in date_info.get('games', []):
            if game.get('status', {}).get('detailedState') != 'Final':
                continue

            games_count += 1
            away_id = game['teams']['away']['team']['id']
            away_name = game['teams']['away']['team']['name']
            home_id = game['teams']['home']['team']['id']
            home_name = game['teams']['home']['team']['name']

            team_names[away_id] = away_name
            team_names[home_id] = home_name

            games_played[away_id] += 1
            games_played[home_id] += 1

            innings = game.get('linescore', {}).get('innings', [])

            for idx, inning in enumerate(innings):
                away_runs = inning.get('away', {}).get('runs', 0)
                home_runs = inning.get('home', {}).get('runs', 0)

                # 1. Away Team (Bats in Top half)
                if away_runs > 0:
                    scoring_opportunities[away_id] += 1
                    # Check if Home team scored in Bottom half of SAME inning
                    if home_runs > 0:
                        shutdown_failures[away_id] += 1
                        runs_scored_in_failures[away_id] += away_runs
                        runs_allowed_in_failures[away_id] += home_runs

                # 2. Home Team (Bats in Bottom half)
                if home_runs > 0:
                    scoring_opportunities[home_id] += 1
                    # Check if Away team scored in Top half of NEXT inning
                    if (idx + 1) < len(innings):
                        next_top_runs = innings[idx + 1].get('away', {}).get('runs', 0)
                        if next_top_runs > 0:
                            shutdown_failures[home_id] += 1
                            runs_scored_in_failures[home_id] += home_runs
                            runs_allowed_in_failures[home_id] += next_top_runs

    print(f"✅ Analyzed {games_count} completed MLB games.\n")

    # Aggregate results
    results = []
    for t_id, name in team_names.items():
        opps = scoring_opportunities[t_id]
        fails = shutdown_failures[t_id]
        gp = games_played[t_id]
        rate = (fails / opps * 100) if opps > 0 else 0.0
        r_scored = runs_scored_in_failures[t_id]
        r_allowed = runs_allowed_in_failures[t_id]
        diff = r_scored - r_allowed

        results.append({
            'name': name,
            'gp': gp,
            'opps': opps,
            'fails': fails,
            'rate': rate,
            'diff': diff
        })

    # Sort by Failure Rate descending (highest failure percentage first)
    results.sort(key=lambda x: x['rate'], reverse=True)

    print("=" * 82)
    print(f"{'RANK':<5} {'TEAM':<26} {'GP':<5} {'SCORING INN':<12} {'FAILURES':<10} {'FAILURE %':<12} {'DIFF':<6}")
    print("=" * 82)

    for rank, r in enumerate(results, 1):
        diff_str = f"+{r['diff']}" if r['diff'] > 0 else str(r['diff'])
        padres_highlight = " 👈 (Padres)" if "Padres" in r['name'] else ""
        print(f"{rank:<5} {r['name']:<26} {r['gp']:<5} {r['opps']:<12} {r['fails']:<10} {r['rate']:<11.1f}% {diff_str:<6}{padres_highlight}")

    print("=" * 82)

if __name__ == "__main__":
    analyze_league_shutdowns()