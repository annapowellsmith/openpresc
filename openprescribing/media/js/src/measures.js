var $ = require('jquery');
var _ = require('underscore');
var mu = require('./measure_utils');
var utils = require('./chart_utils');
var domready = require('domready');
var Highcharts = require('Highcharts');
var chartOptions = require('./highcharts-options');
var L = require('mapbox.js');
var Handlebars = require('handlebars');
var config = require('./config');
Highcharts.setOptions({
  global: {useUTC: false},
});
L.mapbox.accessToken = 'pk.eyJ1IjoiYW5uYXBvd2VsbHNta' +
  'XRoIiwiYSI6ImNzY1VpYkkifQ.LC_IcHpHfOvWOQCuo5t7Hw';

var measures = {
  el: {
    chart: '#charts .chart',
    charts: '#charts',
    mapPanel: 'map-measure',
    perfSummary: '#perfsummary',
    showAll: '#showall',
    sortButtons: '.btn-group > .btn',
    summaryTemplate: '#summary-panel',
    panelTemplate: '#measure-panel',
    noCostSavingWarning: '#no-cost-saving-warning'
  },

  setUp: function() {
    var _this = this;
    _this.isOldIe = utils.getIEVersion();
    var summaryTemplate =
        Handlebars.compile($(_this.el.summaryTemplate).html());
    var panelTemplate =
        Handlebars.compile($(_this.el.panelTemplate).html());
    var NUM_MONTHS_FOR_RANKING = 6;
    var centiles = ['10', '20', '30', '40', '50', '60', '70', '80', '90'];
    var selectedMeasure = window.location.hash;
    _this.allGraphsRendered = false;
    _this.graphsToRenderInitially = 24;
    var options = JSON.parse(document.getElementById('measure-options').innerHTML);
    _this.setUpShowPractices();
    _this.setUpMap(options);

    $.when(
      $.ajax(options.panelMeasuresUrl),
      $.ajax(options.globalMeasuresUrl)
    ).done(function(panelMeasures, globalMeasures) {
      var chartData = panelMeasures[0].measures;
      var globalData = globalMeasures[0].measures;

      _.extend(options,
               mu.getCentilesAndYAxisExtent(globalData, options, centiles));
      chartData = mu.annotateData(chartData, options,
                                  NUM_MONTHS_FOR_RANKING);
      chartData = mu.addChartAttributes(chartData, globalData,
                                        options.globalCentiles, centiles, options,
                                        NUM_MONTHS_FOR_RANKING);
      chartData = mu.sortData(chartData);
      var perf = mu.getPerformanceSummary(chartData, options,
                                          NUM_MONTHS_FOR_RANKING);
      $(_this.el.perfSummary).html(summaryTemplate(perf));
      var html = '';
      _.each(chartData, function(d) {
        html = panelTemplate(d);
        $(d.chartContainerId).append(html);
      });
      $(_this.el.charts)
        .find('a[data-download-chart-id]')
        .on('click', function() {
          return _this.handleDataDownloadClick(
            chartData, $(this).data('download-chart-id')
          );
        });
      _.each(chartData, function(d, i) {
        if (i < _this.graphsToRenderInitially) {
          var chOptions = mu.getGraphOptions(
            d, options, d.is_percentage, chartOptions);
          if (chOptions) {
            new Highcharts.Chart(chOptions);
          }
        }
      });
      $('.loading-wrapper').hide();
      // On long pages, render remaining graphs only after scroll,
      // to stop the page choking on first load.
      $(window).scroll(function() {
        if (_this.allGraphsRendered === false) {
          _.each(chartData, function(d, i) {
            if (i >= _this.graphsToRenderInitially) {
              var chOptions = mu.getGraphOptions(
                d, options, d.is_percentage, chartOptions);
              if (chOptions) {
                new Highcharts.Chart(chOptions);
              }
            }
          });
          _this.allGraphsRendered = true;
        }
      });

      if (options.rollUpBy === 'measure_id') {
        _this.setUpSortGraphs();
      }
      _this.highlightSelectedMeasure(selectedMeasure);
      if (location.search.indexOf('sortBySavings') > -1) {
        $(_this.el.sortButtons).click();
      }
    })
      .fail(function(jqXHR, textStatus, error) {
        console.log('Error ' + error + ' when making request ' + jqXHR);
      });
  },

  highlightSelectedMeasure: function(selectedMeasure) {
    if ( ! selectedMeasure || selectedMeasure === '') return;
    var measureId = '#measure_' + selectedMeasure.substring(selectedMeasure.indexOf('#') + 1);
    if ($(measureId).length === 0) return;
    $('#overlay').fadeIn(300);
    $(measureId).css('z-index', '99999');
    $('html, body').animate({
      scrollTop: $(measureId).offset().top,
    }, 1000);
    $('#overlay').on('click', function() {
      $('#overlay').stop().fadeOut(300);
    });
  },

  setUpShowPractices: function() {
    $(this.el.showAll).on('click', function(e) {
      e.preventDefault();
      $('#child-entities li.hidden').each(function(i, item) {
        $(item).removeClass('hidden');
      });
      $(this).hide();
    });
  },

  setUpMap: function(options) {
    var _this = this;
    if ($('#' + _this.el.mapPanel).length) {
      var map = L.mapbox.map(
        _this.el.mapPanel,
        'mapbox.streets',
        {zoomControl: false}).setView([52.905, -1.79], 6);
      map.scrollWheelZoom.disable();
      var maxZoom = 5;
      if (options.orgType === 'practice') {
        maxZoom = 12;
      }
      var layer = L.mapbox.featureLayer()
          .loadURL(options['orgLocationUrl'])
          .on('ready', function() {
            if (layer.getBounds().isValid()) {
              map.fitBounds(layer.getBounds(), {maxZoom: maxZoom});
              layer.setStyle({fillColor: '#ff00ff',
                              fillOpacity: 0.2,
                              weight: 0.5,
                              color: '#333',
                              radius: 10});
            } else {
              $('#map-container').html('');
            }
          })
          .addTo(map);
    }
  },

  setUpSortGraphs: function() {
    var _this = this;
    var chartsByPercentile = $(_this.el.chart);
    var nonCostSavingCharts = $(chartsByPercentile).filter(function(a) {
      return ! $(this).data('costsaving');
    });
    chartsBySaving = $(_this.el.chart).sort(function(a, b) {
      return $(b).data('costsaving') - $(a).data('costsaving');
    });
    if (nonCostSavingCharts.length === chartsByPercentile.length) {
      chartsBySaving = chartsBySaving.add(
        $(_this.el.noCostSavingWarning).clone().removeClass('hidden')
      );
    }
    $(_this.el.sortButtons).click(function() {
      $(this).addClass('active').siblings().removeClass('active');
      if ($(this).data('orderby') === 'savings') {
        $(_this.el.charts).fadeOut(function() {
          nonCostSavingCharts.hide();
          $(_this.el.charts).html(chartsBySaving).fadeIn();
        });
      } else {
        $(_this.el.charts).fadeOut(function() {
          nonCostSavingCharts.show();
          $(_this.el.charts).html(chartsByPercentile).fadeIn();
        });
      }
    });
  },

  handleDataDownloadClick: function(chartData, chartId) {
    var browserSupported = ! this.isOldIe;
    ga('send', {
      'hitType': 'event',
      'eventCategory': 'measure_data',
      'eventAction': browserSupported ? 'download' : 'failed_download',
      'eventLabel': chartId,
    });
    if (browserSupported) {
      mu.startDataDownload(chartData, chartId);
    } else {
      window.alert('Sorry, you must use a newer web browser to download data');
    }
    return false;
  }

};

domready(function() {
  measures.setUp();
});
