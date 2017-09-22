from collections import OrderedDict, defaultdict
import math
import os

from bs4 import BeautifulSoup, Comment
from jinja2 import Environment, FileSystemLoader
import json
import pandas
from requests import get
from utils import cached

ALL_TEAMS_URL = 'https://www.basketball-reference.com/contracts/'

OPTION_TO_COLORS = {
    'salary-tm': 'black',
    'salary-pl': 'rgb(124, 181, 236)',
    'salary-et': 'rgb(124, 181, 236)',
    '': 'rgb(144, 237, 125)'
}


@cached(3600 * 24 * 7)
def _get_html_contents(url):
    """
    make a request to get the html contents of the given url.
    """
    return get(url).text


# --- UTILITY METHODS FOR EXTRACTING MEANING OUT OF HTML ---

def _sanitize_salary(salary):
    """
    Remove $ and , from salary so that it can be parsed into an int.
    """
    if salary:
        return int(salary.replace('$', '').replace(',', ''))

def _extract_team_name_from_row(row):
    """
    Extract a team name from an html row.
    """
    team_link = row.find('a')['href']
    return str(team_link.split('/')[-1].replace('.html', ''))


def _to_total_salary(salary_data):
    """
    Extract a team's total salary from individual salary data.
    """
    return sum(_['salary'] for _ in salary_data if _['salary'])


class TeamSalaryScraper(object):

    BASE_SALARY_URL = 'https://www.basketball-reference.com/contracts/{0}.html'
    TEAM_URL = 'https://www.basketball-reference.com/teams/{0}/2017.html'
    TEAM_KEY = 'Team Totals'

    def __init__(self, team_name, year_key):
        self.team_name = team_name.upper()
        self.salary_url = self.BASE_SALARY_URL.format(self.team_name)
        self.stats_url = self.TEAM_URL.format(self.team_name)
        self.year_key = year_key

    def _get_per_html(self):
        """
        Return the html to get per data for the given team
        """
        return _get_html_contents(self.stats_url)

    def scrape_ws(self):
        """
        Return a dictionary of player to win share.
        """
        html = self._get_per_html()
        per_scraper = BeautifulSoup(html, 'html.parser')

        advanced_stats = per_scraper.find('div', id='all_advanced').find(text=lambda x: isinstance(x, Comment)).extract()
        data = pandas.read_html(advanced_stats, header=0)[0].to_dict()

        player_to_index = data['Unnamed: 1']
        idx_to_ws = data['WS']

        player_to_ws = {}
        for idx, player in player_to_index.iteritems():
            player_to_ws[player] = round(idx_to_ws.get(idx), 3)

        return player_to_ws

    def _get_salary_html(self):
        """
        Return the html for salary data for the given team.
        """
        return _get_html_contents(self.salary_url)

    def scrape(self):
        """
        Convert the salary html into a list of player dictionaries with relevant attributes.

        example response:
        [{'name': 'LeBron James', 'salary: '33285709', 'option': 'salary_tm'},
         ...
        }]
        """
        print 'scraping data for {0}'.format(self.team_name)
        html = self._get_salary_html()
        salary_scraper = BeautifulSoup(html, 'html.parser')

        # get data-stat attribute of year_key. TODO: break off into its own method.
        data_stat_for_yr = None
        salary_table = salary_scraper.find('table', id='contracts')
        for col in salary_table.findAll('th'):
            if col.text == self.year_key:
                data_stat_for_yr = col['data-stat']
                break

        assert data_stat_for_yr is not None, 'could not find a corresponding column for the given year {0}'.format(year_key)

        players = []
        for player in salary_table.find('tbody').findAll('tr'):
            year_data = player.find('td', {'data-stat': data_stat_for_yr})
            raw_salary = year_data.text

            if raw_salary:
                option = str(year_data['class'][1])
                salary = _sanitize_salary(raw_salary)
            else:
                # free-agent. get last year's salary
                option = 'fa'
                salary = _sanitize_salary(player.find('td', {'data-stat': 'y1'}).text)

            player_text = player.find('th', {'data-stat': 'player'}).find('a')
            name =  player_text.text
            player_status = 'not-active' if player_text.find('em') else 'active'

            players.append({
                'name': name,
                'option': option,
                'salary': salary,
                'player_status': player_status
            })

        return players

    def to_base_series(self, salary_data):
        """
        Convert the basketball-reference salary cap data into a base series object.
        """
        return {
            'name': self.team_name,
            'y': _to_total_salary(salary_data),
            'drilldown': self.team_name
        }

    def to_series_breakdown(self, salary_data):
        """
        Convert the basketball-reference salary cap data into broken down series.

        e.g. {"guaranteed": 100, "player": 10, "team": 20}
        """
        return {
            'Guaranteed': sum([d['salary'] for d in salary_data if d['option'] == '']),
            'Player Option': sum([d['salary'] for d in salary_data if d['option'] in {'salary-pl','salary-et'}]),
            'Team Option': sum([d['salary'] for d in salary_data if d['option'] == 'salary-tm'])
        }

    def to_drilldown(self, salary_data):
        """
        Convert the basketball-reference salary cap data into drilldown objects.
        """
        team_salary = _to_total_salary(salary_data)

        series = {'name': self.team_name, 'y': team_salary, 'drilldown': self.team_name}

        drilldown = {'id': self.team_name, 'data': [], 'name': 'salary'}
        for player in salary_data:
            if player['option'] == 'fa':
                continue

            drilldown['data'].append({
                'name': player['name'],
                'y': player['salary'],
                'color': OPTION_TO_COLORS[player['option']]
            })

        drilldown['data'].sort(key=lambda x: x['y'], reverse=True)
        return series, drilldown


class RawSalaryDataDriver(object):

    def get_raw_salary_data(self, year_key):

        data = []
        for team in get_all_team_names():
            ts = TeamSalaryScraper(team, year_key)
            salary_data = ts.scrape()
            data.append({
                'team': team,
                'player_salaries': salary_data
            })

        return data

    def write_json(self, year_key):

        raw_salary_data = self.get_raw_salary_data(year_key)

        with open('raw_salary_{0}.json'.format(year_key), 'w') as data_file:
            json.dump(obj=raw_salary_data, fp=data_file)


def get_all_team_names():
    """
    Extract all team names ('CLE', 'GSW') into a list
    """
    team_html = _get_html_contents(ALL_TEAMS_URL)
    team_scraper = BeautifulSoup(team_html, 'html.parser')

    teams = []
    teams_table = team_scraper.find('table', id='team_summary')
    for row in teams_table.findAll('td', {'data-stat': 'team_name'}):
        team_link = _extract_team_name_from_row(row)
        teams.append(team_link)
    return teams


def drive_stacked_high_charts(year_key):
    """
    Return a dictionary of options that can be used to render a high charts html object.
    """
    all_teams = get_all_team_names()

    drilldown_data = []
    series_type_to_data = defaultdict(list)

    team_to_total_salary = []
    for team in all_teams:
        team_scraper = TeamSalaryScraper(team, year_key)
        salary_data = team_scraper.scrape()

        drilldown_data.append(team_scraper.to_drilldown(salary_data))
        team_to_total_salary.append([team, _to_total_salary(salary_data)])

    import pdb; pdb.set_trace()
    for team_data in sorted(team_to_total_salary, key=lambda x: x[1], reverse=True):
        team = team_data[0]
        team_scraper = TeamSalaryScraper(team, year_key)
        salary_data = team_scraper.scrape()
        series_breakdown = team_scraper.to_series_breakdown(salary_data)

        for series_type, value in series_breakdown.iteritems():
            series_type_to_data[series_type].append({'name': team, 'y': value, 'drilldown': team})

    series_data = []
    for series_type in ['Player Option', 'Team Option', 'Guaranteed']:
        series_data.append({
            'name': series_type,
            'data': series_type_to_data[series_type]
        })
    return {'series_data': series_data, 'teams': all_teams, 'drilldown_data': drilldown_data}


def to_html(file_name, **kwargs):
    """
    Return an html file with the included data to be rendered by Highcharts.
    """
    loader = FileSystemLoader(os.getcwd())
    template_file = 'templates/{0}'.format(file_name)
    template = Environment(loader=loader, trim_blocks=True).get_template(template_file)
    return template.render(**kwargs)


@cached(3600 * 24 * 7)
def get_all_ws():
    all_ws = {}
    for t in get_all_team_names():
        team_scraper = TeamSalaryScraper(t, year_key)
        ws_data = team_scraper.scrape_ws()
        all_ws.update(ws_data)
    return all_ws


def drive_scatter(year_key):
    """
    Return a scatter plot for the given team.
    """
    all_ws = get_all_ws()

    series_data = []
    for team in get_all_team_names():
        salary_data = TeamSalaryScraper(team, year_key).scrape()

        for player in salary_data:
            player_name = player['name']
            if player_name in all_ws:
                scatter_point = {'name': player_name, 'x': player['salary'], 'y': all_ws[player_name]}
                series_data.append(scatter_point)

    return {'series_data': {'data': series_data, 'name': 'players'}}


if __name__ == '__main__':
    year_key = '2018-19'
    """
    high_chart = drive_scatter(year_key)
    chart_html = to_html('team_salary_scatter_html.jm', **high_chart)

    with open('salary_scatter_{0}.html'.format(year_key), 'w') as html:
        html.write(chart_html)
    """

    high_charts = drive_stacked_high_charts(year_key)
    chart_html = to_html('team_salary_scatter_html.jm', **high_charts)

    print chart_html

    with open('team_salary_{0}_stacked.html'.format(year_key), 'w') as html:
        html.write(chart_html)
