let rows = [];
let table;
let tablebody;

$(document).ready(function(){



    table = document.getElementById("resultsTable");
    //https://stackoverflow.com/questions/18333427/how-to-insert-row-in-html-table-body-in-javascript
    tablebody = document.getElementsByTagName("tbody")[0];


    //typeashead configuration for add book form
    $("#q").typeahead({
        highlight: true,
        minLength: 1
    },
    {
        //what is displayed when an option is selected.
        display: function(suggestion) {
          return (mark_undefine(suggestion.volumeInfo.title) + " ,  " + mark_undefine(suggestion.volumeInfo.subtitle) + " ,  " +
              mark_undefine(suggestion.volumeInfo.authors) + " ,  " + mark_undefine(suggestion.volumeInfo.publishedDate)) ;
        },
        limit: 20,
        source: books,
        templates: {
          //this how the suggesstion in the suggestion menu appear
            suggestion: Handlebars.compile(
                '<div>{{volumeInfo.title}}, {{#if volumeInfo.subtitle}}{{volumeInfo.subtitle}},{{/if}} {{#if volumeInfo.authors}}{{volumeInfo.authors}},{{/if}} {{volumeInfo.publishedDate}} </div>'
            ),
            empty: '<div class="empty-message"> unable to find a book that matches your query!</div>'
        }
    });


    //second typeahead for books to borrow lookup

    $("#bq").typeahead({
      highlight: true,
      minLength: 1
    },
    {

        display: function(suggestion){return (suggestion.title+ ", "+ suggestion.subtitle);},
        limit: 10,
        source: usersbooks,
        templates: {
          suggestion: Handlebars.compile(
            '<div>{{title}}, {{#if subtitle}}{{subtitle}},{{/if}} {{#if authors}}{{authors}},{{/if}} {{publishedDate}}</div>'
          ),
          empty: '<div class="empty-message"> Couldn\'t find any entries with this details. </div>'
        }
    });

    $("#bq").on("typeahead:selected", function(eventObject, suggestion, name) {
        //on selection my input box value is automatically set to display.

        get_results(suggestion.title, suggestion.subtitle)
    });

    $("#all").click(function() {

      get_results('', '')

    })


});

function books(query, syncResults, asyncResults)
{

  var googleAPI = "https://www.googleapis.com/books/v1/volumes?q="+query+"&fields=items(volumeInfo/title,volumeInfo/subtitle,volumeInfo/authors,volumeInfo/publishedDate)&key="+key;

// Make a ajax call to get the json data as response.
  $.getJSON(googleAPI)
  .done(function(data,textStatus, jqXHR) {

        // Call typeahead's callback with search results (i.e., places)
        asyncResults(data.items);
    })
    .fail(function(jqXHR, textStatus, errorThrown) {
        console.log(errorThrown.toString());
        asyncResults([]);
    });
}

function usersbooks(query, synchResults, asyncResults)
{
  let parameters = {
      q: query
  };
  $.getJSON("/search", parameters)
  .done(function(data, textStatus, jqXHR) {

      // Call typeahead's callback with search results (i.e., places)
      asyncResults(data);
  })
  .fail(function(jqXHR, textStatus, errorThrown)  {
      console.log(errorThrown.toString());
      asyncResults([]);
  });
}




function get_results(title, subtitle)
{
    let parameters = {
        title: title,
        subtitle:subtitle
    };
    $.getJSON("/searchresults", parameters)
    .done(function(data, textStatus, jqXHR) {

      update_table(data);
    })
    .fail(function(jqXHR, textStatus, errorThrown) {
        console.log(errorThrown.toString());

    });
}



function update_table(data)
{
    //https://stackoverflow.com/questions/18333427/how-to-insert-row-in-html-table-body-in-javascript
    removeRows();
    table.tHead.hidden = false;
    document.getElementsByName('borrow')[0].hidden = false;
    document.getElementsByName('searchresults')[0].hidden = false;
    for (let index in data)
    {
        addRows(data, index);
    }
}

function removeRows()
{
    //this also considers the header row so the value will always be added 1.
    //https://stackoverflow.com/questions/18333427/how-to-insert-row-in-html-table-body-in-javascript
      while(tablebody.rows.length > 0)
      {
          tablebody.deleteRow(0);
      }

}

function addRows(data, index)
{
    let state = " ";
    let row = tablebody.insertRow(index);
    let column1 = row.insertCell(0);
    let column2 = row.insertCell(1);
    let column3 = row.insertCell(2);
    let column4 = row.insertCell(3);
    let column5 = row.insertCell(4);
    let column6 = row.insertCell(5);
    let column7 = row.insertCell(6);

    if (data[index]['state'] == "on loan" || data[index]['state'] == "on Hold" || data[index]['state'] == "overdue" )
      {
         state = "disabled";
      }

    //select column
    column1.innerHTML = "<input type='radio' required name='book_id' value='" + data[index]['id'] + "'" + state  + "/>";

    //book details column
    column2.innerHTML = data[index]['title'] + ', '
    if (data[index]['subtitle'])
      {
        column2.innerHTML += data[index]['subtitle'] + ', '
      }
    if (data[index]['authors'])
      {
        column2.innerHTML += data[index]['authors'] + ', '
      }
    column2.innerHTML += data[index]['publishedDate'];
    column3.innerHTML  = data[index]['username'];

    //loan period column
    if (parseInt(data[index]['lendfor']) > 1)
    {
          column4.innerHTML = data[index]['lendfor'] + ' days ';
    }
    else {
        column4.innerHTML = data[index]['lendfor'] + ' day ';
    }

    //book state column
    column5.innerHTML = data[index]['state'];
    //review column
    column6.innerHTML = data[index]['review'] ;
    //notes column
    column7.innerHTML = data[index]['notes'];
}


//determines how undefined fields are stored in my database
function mark_undefine(field)
{
    if (typeof(field) == "undefined")
    {
        return field = "";
    }
    else
    {
        return field;
    }
}
